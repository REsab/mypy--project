import os
import time
import subprocess
import cv2
import numpy as np
import random

# ================= 配置区 =================
# ADB 路径需指向你 Mac 上的具体位置
ADB_PATH = "/Users/resab/mac/scrcpy-macos-x86_64-v3.3.1/adb"
APP_PACKAGE = "com.luna.music"
APP_ACTIVITY = "com.luna.biz.main.main.MainActivity"

# 图像素材配置
IMG_DIR = "img-k80"
TEMPLATES = {
    "reward": os.path.join(IMG_DIR, "领取奖励.png"),  # 需更新为“继续观看”或“领取奖励”的截图
    "success": os.path.join(IMG_DIR, "领取成功.png"),
    "playing": os.path.join(IMG_DIR, "秒后可领取奖励.png")
}

# 屏幕参数（脚本启动后会自动通过 ADB 更新）
SCREEN_W = 1280
SCREEN_H = 2768


# =========================================

def run_adb(command):
    """封装 ADB 调用"""
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def update_screen_size():
    """动态获取手机分辨率以适配不同机型"""
    global SCREEN_W, SCREEN_H
    res = run_adb("shell wm size")
    output = res.stdout.decode('utf-8')
    if "size:" in output:
        size_str = output.split("size: ")[1].strip()
        SCREEN_W, SCREEN_H = map(int, size_str.split('x'))
        print(f"[SYSTEM] 检测到设备分辨率: {SCREEN_W}x{SCREEN_H}")


def get_ratio_pos(w_ratio, h_ratio):
    """根据比例计算绝对坐标，解决新手机适配问题"""
    return (int(SCREEN_W * w_ratio), int(SCREEN_H * h_ratio))


def random_tap(x, y, w, h):
    """在目标范围内执行随机点击"""
    offset_x = random.randint(-int(w * 0.2), int(w * 0.2))
    offset_y = random.randint(-int(h * 0.2), int(h * 0.2))
    final_x, final_y = x + offset_x, y + offset_y
    print(f"  [ACTION] 👉 点击坐标: ({final_x}, {final_y})")
    run_adb(f"shell input tap {final_x} {final_y}")


def get_screen_pos(name, template_path, threshold=0.75):
    """带 ROI 区域过滤的图像识别"""
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")

    screen_rgb = cv2.imread("screen.png")
    template_rgb = cv2.imread(template_path)
    if screen_rgb is None or template_rgb is None: return None

    # --- 针对长屏手机优化 ROI 比例 ---
    if name == "reward":
        # 弹窗按钮通常在屏幕中心偏下 (25% - 80% 高度)
        roi_top, roi_bottom = int(SCREEN_H * 0.25), int(SCREEN_H * 0.8)
    elif name == "playing" or name == "success":
        # 顶部状态信息 (0% - 35% 高度)
        roi_top, roi_bottom = 0, int(SCREEN_H * 0.35)
    else:
        roi_top, roi_bottom = 0, SCREEN_H

    screen_roi = screen_rgb[roi_top:roi_bottom, 0:SCREEN_W]
    res = cv2.matchTemplate(cv2.cvtColor(screen_roi, cv2.COLOR_BGR2GRAY),
                            cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        print(f"  [LOG] 命中 [{name}]: 相似度 {max_val:.4f}")
        h, w = template_rgb.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2 + roi_top, w, h)
    return None


def wait_for_ad_finish(max_wait=70, interval=6):
    """动态监测广告播放状态"""
    print(f"⏳ 广告播放监测中...")
    start_time = time.time()
    while (time.time() - start_time) < max_wait:
        time.sleep(interval)
        # 识别“秒后可领取奖励”
        if get_screen_pos("playing", TEMPLATES["playing"], threshold=0.7):
            print(f"  [STATUS] 📺 广告正在播放...")
            continue
        # 检查是否出现结束按钮
        if get_screen_pos("reward", TEMPLATES["reward"]) or get_screen_pos("success", TEMPLATES["success"]):
            print("  [STATUS] ✨ 监测到按钮，广告已结束")
            return True
    return False


def main():
    print("🚀 汽水音乐自动化脚本【新手机适配版】启动...")
    update_screen_size()
    fail_count = 0

    # 比例化计算首页固定坐标
    # 之前 1080 宽度的 818 坐标对应约 0.75 比例
    COORD_FREE_VIP = get_ratio_pos(0.75, 0.07)
    COORD_CLOSE_SAFE = get_ratio_pos(0.92, 0.07)

    while True:
        # 前台检查
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] 正在启动 App...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(10)

        print("\n--- 轮询扫描状态 ---")

        # 1. 尝试寻找“继续观看/领取奖励”按钮
        res_reward = get_screen_pos("reward", TEMPLATES["reward"])
        if res_reward:
            random_tap(*res_reward)
            fail_count = 0
            wait_for_ad_finish()
            continue

        # 2. 尝试寻找“领取成功”或关闭 X
        res_success = get_screen_pos("success", TEMPLATES["success"])
        if res_success:
            random_tap(*res_success)
            fail_count = 0
            time.sleep(5)
            continue

        # 3. 保底逻辑：点击首页入口或清除弹窗
        print("🔍 未见目标按钮，执行保底点击...")
        run_adb(f"shell input tap {COORD_FREE_VIP[0]} {COORD_FREE_VIP[1]}")
        run_adb(f"shell input tap {COORD_CLOSE_SAFE[0]} {COORD_CLOSE_SAFE[1]}")

        fail_count += 1
        if fail_count >= 8:  # 约 1.5 分钟无响应则重启
            print("❌ 脚本卡死，强制重启中...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            fail_count = 0

        time.sleep(6)


if __name__ == "__main__":
    main()