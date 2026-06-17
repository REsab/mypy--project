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

IMG_DIR = "img-k80"
TEMPLATES = {
    "reward": os.path.join(IMG_DIR, "继续观看.png"),  # 弹窗按钮1：继续观看
    "action_reward": os.path.join(IMG_DIR, "领取奖励.png"),  # 弹窗按钮2：当前截图中的绿色大按钮
    "free_listen": os.path.join(IMG_DIR, "日免费听.png"),  # 新增：弹窗核心文本特征
    "success": os.path.join(IMG_DIR, "领取成功x.png"),  # 建议用右上角带X的“领取成功”局部图
    "playing": os.path.join(IMG_DIR, "秒后可领取奖励.png")
}

SCREEN_W = 1280
SCREEN_H = 2768


# =========================================

def run_adb(command):
    """封装 ADB 调用"""
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def update_screen_size():
    """动态获取手机分辨率"""
    global SCREEN_W, SCREEN_H
    res = run_adb("shell wm size")
    output = res.stdout.decode('utf-8')
    if "size:" in output:
        size_str = output.split("size: ")[1].strip()
        SCREEN_W, SCREEN_H = map(int, size_str.split('x'))
        print(f"[SYSTEM] 检测到设备分辨率: {SCREEN_W}x{SCREEN_H}")


def get_ratio_pos(w_ratio, h_ratio):
    """根据比例计算绝对坐标"""
    return (int(SCREEN_W * w_ratio), int(SCREEN_H * h_ratio))


def random_tap(x, y, w=20, h=20):
    """在目标范围内执行随机点击"""
    offset_x = random.randint(-int(w * 0.2), int(w * 0.2)) if w > 0 else 0
    offset_y = random.randint(-int(h * 0.2), int(h * 0.2)) if h > 0 else 0
    final_x, final_y = x + offset_x, y + offset_y
    print(f"  [ACTION] 👉 点击坐标: ({final_x}, {final_y})")
    run_adb(f"shell input tap {final_x} {final_y}")


def capture_screen():
    """单次截屏，全脚本复用以提升运行速度"""
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")
    return cv2.imread("screen.png")


def match_template_in_img(screen_rgb, name, template_path, threshold=0.72):
    """全屏图像识别（降低阈值至0.72提高抗干扰能力）"""
    template_rgb = cv2.imread(template_path)
    if screen_rgb is None or template_rgb is None:
        return None

    # 直接全屏扫描，防止长屏 ROI 错位
    res = cv2.matchTemplate(cv2.cvtColor(screen_rgb, cv2.COLOR_BGR2GRAY),
                            cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        h, w = template_rgb.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2, w, h, max_val)
    return None


def wait_for_ad_finish(max_wait=70, interval=5):
    """动态监测广告播放状态"""
    print(f"⏳ 广告播放监测中...")
    start_time = time.time()
    while (time.time() - start_time) < max_wait:
        time.sleep(interval)
        screen_img = capture_screen()

        # 1. 还在播放则继续等待
        if match_template_in_img(screen_img, "playing", TEMPLATES["playing"], threshold=0.68):
            print(f"  [STATUS] 📺 广告正在播放...")
            continue

        # 2. 出现了任意弹窗特征或结束特征，结束等待
        if match_template_in_img(screen_img, "reward", TEMPLATES["reward"]) or \
                match_template_in_img(screen_img, "action_reward", TEMPLATES["action_reward"]) or \
                match_template_in_img(screen_img, "free_listen", TEMPLATES["free_listen"]) or \
                match_template_in_img(screen_img, "success", TEMPLATES["success"]):
            print("  [STATUS] ✨ 监测到画面状态发生改变，退出等待")
            return True
    return False


def main():
    print("🚀 汽水音乐纯净看广告脚本【弹窗加强版】启动...")
    update_screen_size()

    # 右上角安全关闭坐标
    COORD_CLOSE_SAFE = get_ratio_pos(0.92, 0.07)
    fail_count = 0

    while True:
        # App 应用前台保活
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] App 未在前台，正在重新启动...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(8)
            fail_count = 0

        print("\n--- 正在扫描当前画面状态 ---")
        screen_img = capture_screen()

        # 扫描所有可能的特征
        reward_match = match_template_in_img(screen_img, "reward", TEMPLATES["reward"])
        action_match = match_template_in_img(screen_img, "action_reward", TEMPLATES["action_reward"])
        free_listen_match = match_template_in_img(screen_img, "free_listen", TEMPLATES["free_listen"])
        success_match = match_template_in_img(screen_img, "success", TEMPLATES["success"])

        # ====== 核心判定逻辑（包含“日免费听”） =====

        # 状况 A：只要命中“继续观看”、“领取奖励”大绿按钮、或者检测到“日免费听”文本 -> 统统判定为【挽留弹窗】
        if reward_match or action_match or free_listen_match:
            print(f"  [🎯 状态] 判定为 -> 【挽留/看广告弹窗】")
            if free_listen_match:
                print(f"  └─ 🔍 触发特征: [日免费听] (相似度: {free_listen_match[4]:.4f})")

            # 决定点击哪里：优先点击捕获到的实体按钮，都没有就点中间偏下保底
            if reward_match:
                random_tap(reward_match[0], reward_match[1], reward_match[2], reward_match[3])
            elif action_match:
                random_tap(action_match[0], action_match[1], action_match[2], action_match[3])
            else:
                # 识别到了“日免费听”文字，但按钮没识别到，直接根据比例点中间偏下绿色大按钮的大概位置
                print("  └─ ⚠️ 未识别到明确按钮坐标，执行保底位置点击")
                tap_pos = get_ratio_pos(0.5, 0.54)
                random_tap(tap_pos[0], tap_pos[1], w=10, h=10)

            fail_count = 0
            wait_for_ad_finish()
            continue

        # 状况 B：仅“领取成功”命中，且没有任何弹窗特征 -> 真正的广告播放完毕，点右上角关闭
        elif success_match:
            print(f"  [🎯 状态] 仅命中 [领取成功] (相似度: {success_match[4]:.4f}) -> 广告真正完成")
            print("  [ACTION] 🛑 点击右上角关闭按钮")
            random_tap(COORD_CLOSE_SAFE[0], COORD_CLOSE_SAFE[1], w=10, h=10)
            fail_count = 0
            time.sleep(4)
            continue

        # ====== 保底与异常处理 =====
        print("  [STATUS] 未识别到任何目标状态...")
        fail_count += 1

        if fail_count >= 5:
            print("  [WARNING] 画面可能卡死，尝试点一次右上角关闭...")
            random_tap(COORD_CLOSE_SAFE[0], COORD_CLOSE_SAFE[1], w=10, h=10)

        if fail_count >= 10:
            print("❌ 脚本彻底卡死，强制重启 App...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            fail_count = 0

        time.sleep(5)


if __name__ == "__main__":
    main()