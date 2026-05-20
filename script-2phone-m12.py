import os
import time
import subprocess
import cv2
import numpy as np
import random

# ================= 配置区 =================
ADB_PATH = "/Users/resab/mac/scrcpy-macos-x86_64-v3.3.1/adb"
APP_PACKAGE = "com.luna.music"
APP_ACTIVITY = "com.luna.biz.main.main.MainActivity"

# 固定坐标点：首页的“免费听歌”入口
COORD_FREE_VIP = (818, 182)
# 保底位：通常是屏幕右上角的关闭位置（降低其乱点频率）
COORD_CLOSE_SAFE = (1050, 185)

# 图像素材配置
IMG_DIR = "img"
TEMPLATES = {
    "reward": os.path.join(IMG_DIR, "领取奖励.png"),
    "success": os.path.join(IMG_DIR, "领取成功.png"),
    "playing": os.path.join(IMG_DIR, "秒后可领取奖励.png"),
    "keep_watching": os.path.join(IMG_DIR, "继续观看.png")  # ✨ 新增：挽留弹窗处理
}


# =========================================

def run_adb(command):
    """封装 ADB 调用"""
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def random_tap(x, y, w, h):
    """在目标范围内执行随机点击"""
    offset_x = random.randint(-int(w * 0.2), int(w * 0.2))
    offset_y = random.randint(-int(h * 0.2), int(h * 0.2))
    final_x = x + offset_x
    final_y = y + offset_y
    print(f"  [ACTION] 👉 执行点击: ({final_x}, {final_y})")
    run_adb(f"shell input tap {final_x} {final_y}")


def get_screen_pos(name, template_path, threshold=0.85):
    """核心识别函数：优化了区域过滤 (ROI)"""
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")

    screen_rgb = cv2.imread("screen.png")
    template_rgb = cv2.imread(template_path)

    if screen_rgb is None or template_rgb is None:
        return None

    screen_h, screen_w = screen_rgb.shape[:2]
    temp_h, temp_w = template_rgb.shape[:2]

    # --- 物理区域过滤 (ROI) ---
    if name == "reward":
        roi_top, roi_bottom = int(screen_h * 0.45), screen_h
    elif name == "playing" or name == "success":
        # ✨ 优化：放宽顶部检测区域到 45%，防止漏掉不同广告位置的倒计时
        roi_top, roi_bottom = 0, int(screen_h * 0.45)
    elif name == "keep_watching":
        # ✨ 新增：继续观看弹窗一般在屏幕中央
        roi_top, roi_bottom = int(screen_h * 0.3), int(screen_h * 0.7)
    else:
        roi_top, roi_bottom = 0, screen_h

    screen_roi = screen_rgb[roi_top:roi_bottom, 0:screen_w]
    screen_gray = cv2.cvtColor(screen_roi, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY)

    res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    # 识别“倒计时文字”和“继续观看”时，阈值稍微放宽，防止由于画质模糊匹配失败
    current_threshold = 0.75 if name in ["playing", "keep_watching"] else threshold

    if max_val >= current_threshold:
        print(f"  [LOG] 匹配成功 [{name}]: 相似度 {max_val:.4f}")
        center_x = max_loc[0] + temp_w // 2
        center_y = max_loc[1] + temp_h // 2 + roi_top
        return (center_x, center_y, temp_w, temp_h)

    return None


def wait_for_ad_finish(max_wait=75, interval=6):
    """动态监测广告：加入挽留弹窗的主动中断检测"""
    print(f"⏳ 进入动态监测模式 (最大等待 {max_wait}s)...")
    start_time = time.time()

    while (time.time() - start_time) < max_wait:
        time.sleep(interval)

        # ✨ 优化检测：如果误触弹出了“继续观看”，立刻中断等待，回到主循环去点击它
        res_keep = get_screen_pos("keep_watching", TEMPLATES["keep_watching"])
        if res_keep:
            print("  [ALERT] ⚠️ 发现挽留弹窗，中断等待，准备修正！")
            return False

        if get_screen_pos("playing", TEMPLATES["playing"]):
            print(f"  [STATUS] 📺 广告还在播放中...")
            continue

        if get_screen_pos("reward", TEMPLATES["reward"]) or get_screen_pos("success", TEMPLATES["success"]):
            print("  [STATUS] ✨ 监测到结算标志，广告提前结束")
            return True

    print("⏰ 到达最大时长，自动退出监测")
    return False


def main():
    print("🚀 汽水音乐自动化脚本强化版启动...")
    fail_count = 0

    while True:
        # App 前台检查
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] App 未在前台，执行强制启动...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            time.sleep(2)
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(12)

        print("\n--- 轮询扫描状态 ---")

        # 【特高优先级】处理挽留弹窗（把乱点出来的尴尬弹窗点回去）
        res_keep = get_screen_pos("keep_watching", TEMPLATES["keep_watching"])
        if res_keep:
            print(f"🚨 状态：检测到挽留弹窗！点击 [继续观看] 恢复广告...")
            random_tap(*res_keep)
            fail_count = 0
            time.sleep(2)
            continue

        # 【高优先级】绿色领取奖励按钮
        res_reward = get_screen_pos("reward", TEMPLATES["reward"])
        if res_reward:
            print(f"🎯 状态：需要 [领取奖励]")
            random_tap(*res_reward)
            fail_count = 0
            wait_for_ad_finish()
            continue

        # 【次高优先级】领取成功按钮
        res_success = get_screen_pos("success", TEMPLATES["success"])
        if res_success:
            print(f"🎯 状态：广告已领，点击 [领取成功] 关闭...")
            random_tap(*res_success)
            fail_count = 0
            time.sleep(5)
            continue

        # 【低保逻辑】没有任何目标时
        print(f"🔍 屏幕未见目标，等待观察... (当前空转计数: {fail_count}/5)")

        # ✨ 优化：前 3 次找不到目标时，只盲点首页入口，绝对不去碰右上角的关闭图标！
        if fail_count < 3:
            print("⚠️ 疑似bug...")
            run_adb(f"shell input tap {COORD_FREE_VIP[0]} {COORD_FREE_VIP[1]}")
        else:
            # 只有连续 4 次（近 30 秒）全屏毫无动静，才允许去点一次 COORD_CLOSE_SAFE 保底
            print("⚠️ 疑似真卡死，尝试执行右上角关闭保底...")
            run_adb(f"shell input tap {COORD_CLOSE_SAFE[0]} {COORD_CLOSE_SAFE[1]}")

        fail_count += 1
        if fail_count >= 5:
            print("❌ 连续卡死无反应，执行重启程序...")
            fail_count = 0
            run_adb(f"force-stop {APP_PACKAGE}")

        time.sleep(6)


if __name__ == "__main__":
    main()