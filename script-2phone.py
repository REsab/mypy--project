import os
import time
import subprocess
import cv2
import numpy as np

# ================= 配置区 =================
ADB_PATH = "/Users/resab/mac/scrcpy-macos-x86_64-v3.3.1/adb"
APP_PACKAGE = "com.luna.music"
APP_ACTIVITY = "com.luna.biz.main.main.MainActivity"

COORD_FREE_VIP = (818, 182)
COORD_CLOSE_SAFE = (1050, 185)

IMG_DIR = "img"
TEMPLATES = {
    "reward": os.path.join(IMG_DIR, "领取奖励.png"),
    "success": os.path.join(IMG_DIR, "领取成功.png")
}


# =========================================

def run_adb(command):
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def get_screen_pos(name, template_path, threshold=0.85):
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")

    screen_rgb = cv2.imread("screen.png")
    template_rgb = cv2.imread(template_path)

    if screen_rgb is None or template_rgb is None:
        return None

    screen_gray = cv2.cvtColor(screen_rgb, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY)

    res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    print(f"  [LOG] 比对 [{name}]: 相似度 {max_val:.4f}")

    if max_val >= threshold:
        h, w = template_gray.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return None


def wait_for_ad_finish(max_wait=60, interval=10):
    """
    动态等待广告结束
    max_wait: 最大等待总时长
    interval: 轮询间隔
    """
    print(f"⏳ 广告播放中，进入动态监测模式 (最大等待 {max_wait}s)...")
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        print(f"  [CHECK] 已等待 {elapsed}s，正在扫描结算按钮...")

        # 广告播完的标志通常是出现“领取成功”或“领取奖励”
        # 我们这里优先检查“领取成功”来作为广告结束的信号
        if get_screen_pos("success", TEMPLATES["success"]):
            print(f"✨ 检测到广告已结束！耗时约 {elapsed}s")
            return True

        # 如果广告直接跳到了奖励页面（挽留弹窗）
        if get_screen_pos("reward", TEMPLATES["reward"]):
            print(f"✨ 广告已结束并直接跳转到奖励页面！耗时约 {elapsed}s")
            return True

    print(f"⏰ 到达最大等待时间 {max_wait}s，强制继续...")
    return False


def main():
    print("🚀 汽水音乐【动态轮询版】启动...")
    consecutive_fail_count = 0

    while True:
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] 正在启动 App...")
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(10)

        print("\n--- 优先级扫描中 ---")

        # 1. 优先找 [领取奖励] 绿按钮
        pos_reward = get_screen_pos("reward", TEMPLATES["reward"])
        if pos_reward:
            print(f"🎯 命中 [领取奖励] {pos_reward}")
            run_adb(f"shell input tap {pos_reward[0]} {pos_reward[1]}")
            consecutive_fail_count = 0

            # 【优化点】改为动态等待
            wait_for_ad_finish(max_wait=65, interval=10)
            continue

            # 2. 找 [领取成功] (关闭 X)
        pos_success = get_screen_pos("success", TEMPLATES["success"])
        if pos_success:
            print(f"🎯 命中 [领取成功] {pos_success}")
            run_adb(f"shell input tap {pos_success[0]} {pos_success[1]}")
            consecutive_fail_count = 0
            time.sleep(5)
            continue

        # 3. 兜底逻辑
        print("🔍 未发现目标，尝试首页入口...")
        run_adb(f"shell input tap {COORD_FREE_VIP[0]} {COORD_FREE_VIP[1]}")
        run_adb(f"shell input tap {COORD_CLOSE_SAFE[0]} {COORD_CLOSE_SAFE[1]}")

        consecutive_fail_count += 1
        if consecutive_fail_count >= 6:
            print("❌ 卡死重启...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            consecutive_fail_count = 0
            time.sleep(2)

        time.sleep(5)


if __name__ == "__main__":
    main()