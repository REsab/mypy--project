import os
import time
import subprocess
import cv2
import numpy as np
import random  # 引入随机数模块

# ================= 配置区 =================
# ADB 路径需指向你 Mac 上的具体位置
ADB_PATH = "/Users/resab/mac/scrcpy-macos-x86_64-v3.3.1/adb"
APP_PACKAGE = "com.luna.music"
APP_ACTIVITY = "com.luna.biz.main.main.MainActivity"

# 固定坐标点：首页的“免费听歌”入口
COORD_FREE_VIP = (818, 182)
# 保底位：通常是屏幕右上角的关闭位置
COORD_CLOSE_SAFE = (1050, 185)

# 图像素材配置
IMG_DIR = "img"
TEMPLATES = {
    "reward": os.path.join(IMG_DIR, "领取奖励.png"),
    "success": os.path.join(IMG_DIR, "领取成功.png"),
    "playing": os.path.join(IMG_DIR, "秒后可领取奖励.png")
}


# =========================================

def run_adb(command):
    """封装 ADB 调用"""
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def random_tap(x, y, w, h):
    """
    在目标范围内执行随机点击
    x, y: 匹配到的中心点
    w, h: 模板图片的宽高
    """
    # 在按钮宽高的 30% 范围内进行随机偏移，确保点击点始终在按钮内
    offset_x = random.randint(-int(w * 0.3), int(w * 0.3))
    offset_y = random.randint(-int(h * 0.3), int(h * 0.3))

    final_x = x + offset_x
    final_y = y + offset_y

    print(f"  [ACTION] 👉 执行点击坐标: ({final_x}, {final_y}) (原始中心: {x}, {y}, 随机偏移: {offset_x}, {offset_y})")
    run_adb(f"shell input tap {final_x} {final_y}")


def get_screen_pos(name, template_path, threshold=0.85):
    """
    核心识别函数：带区域过滤 (ROI) 且返回完整尺寸信息
    """
    # 1. 实时截取手机屏幕
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")

    screen_rgb = cv2.imread("screen.png")
    template_rgb = cv2.imread(template_path)

    if screen_rgb is None or template_rgb is None:
        return None

    screen_h, screen_w = screen_rgb.shape[:2]
    temp_h, temp_w = template_rgb.shape[:2]

    # --- 物理区域过滤 (ROI)：只在按钮可能出现的区域寻找，排除干扰 ---
    if name == "reward":
        # 绿色大按钮只出现在下半部分
        roi_top, roi_bottom = int(screen_h * 0.45), screen_h
    elif name == "playing" or name == "success":
        # 顶部倒计时和关闭按钮只在顶部区域
        roi_top, roi_bottom = 0, int(screen_h * 0.35)
    else:
        roi_top, roi_bottom = 0, screen_h

    # 裁剪图像：只处理感兴趣的区域
    screen_roi = screen_rgb[roi_top:roi_bottom, 0:screen_w]
    screen_gray = cv2.cvtColor(screen_roi, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY)

    # 2. OpenCV 模板匹配
    res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    # 动态调整阈值，倒计时文字识别稍放宽
    current_threshold = 0.75 if name == "playing" else threshold

    if max_val >= current_threshold:
        print(f"  [LOG] 匹配成功 [{name}]: 相似度 {max_val:.4f}")
        # 计算全屏坐标
        center_x = max_loc[0] + temp_w // 2
        center_y = max_loc[1] + temp_h // 2 + roi_top
        return (center_x, center_y, temp_w, temp_h)

    return None


def wait_for_ad_finish(max_wait=70, interval=8):
    """
    动态监测广告：每隔 8 秒看一次屏幕，灵活退出
    """
    print(f"⏳ 进入动态监测模式 (最大等待 {max_wait}s)...")
    start_time = time.time()

    while (time.time() - start_time) < max_wait:
        time.sleep(interval)

        # 如果还在播（有倒计时文字），继续循环
        if get_screen_pos("playing", TEMPLATES["playing"]):
            print(f"  [STATUS] 📺 广告还在播放中...")
            continue

        # 广告结束的两个标志：出现绿按钮或出现“领取成功”
        if get_screen_pos("reward", TEMPLATES["reward"]) or get_screen_pos("success", TEMPLATES["success"]):
            print("  [STATUS] ✨ 监测到结算标志，广告提前结束")
            return True

    print("⏰ 到达最大时长，自动退出监测")
    return False


def main():
    print("🚀 汽水音乐自动化脚本启动...")
    fail_count = 0

    while True:
        # 检查 App 是否在前台
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] App 未在前台，执行强制启动...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            time.sleep(2)
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(12)  # 给 12 秒启动时间

        print("\n--- 轮询扫描状态 ---")

        # 【最高优先级】绿色领取奖励按钮：这意味着可以开始下一轮广告了
        res_reward = get_screen_pos("reward", TEMPLATES["reward"])
        if res_reward:
            print(f"🎯 状态：需要 [领取奖励]")
            random_tap(*res_reward)  # 使用解包语法传入坐标和宽高
            fail_count = 0
            wait_for_ad_finish()  # 点完奖励，直接进广告动态等待
            continue

        # 【次高优先级】领取成功按钮：通常是点击 X 关闭广告后的过渡状态
        res_success = get_screen_pos("success", TEMPLATES["success"])
        if res_success:
            print(f"🎯 状态：广告已领，点击 [领取成功] 关闭...")
            random_tap(*res_success)
            fail_count = 0
            time.sleep(5)  # 等待 5 秒让“挽留弹窗”出来
            continue

        # 【低保逻辑】既没成功也没奖励，尝试点一下首页入口位置
        print("🔍 屏幕未见目标，尝试保底逻辑...")
        run_adb(f"shell input tap {COORD_FREE_VIP[0]} {COORD_FREE_VIP[1]}")
        run_adb(f"shell input tap {COORD_CLOSE_SAFE[0]} {COORD_CLOSE_SAFE[1]}")

        fail_count += 1
        if fail_count >= 6:  # 连续 1 分钟没反应就重启
            print("❌ 连续卡死，执行重启程序...")
            fail_count = 0
            # 重启逻辑会由下次循环头部的“前台检测”触发
            run_adb(f"shell am force-stop {APP_PACKAGE}")

        time.sleep(5)


if __name__ == "__main__":
    main()