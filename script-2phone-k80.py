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
    "reward": os.path.join(IMG_DIR, "继续观看.png"),
    "action_reward": os.path.join(IMG_DIR, "领取奖励.png"),
    "free_listen": os.path.join(IMG_DIR, "日免费听.png"),
    "dialog_close": os.path.join(IMG_DIR, "弹窗关闭.png"),  # ✨ 新增：弹窗正下方的灰色圆圈X号
    "success": os.path.join(IMG_DIR, "领取成功x.png"),
    "playing": os.path.join(IMG_DIR, "秒后可领取奖励.png")
}

SCREEN_W = 1280
SCREEN_H = 2772


# =========================================

def run_adb(command):
    return subprocess.run(f"{ADB_PATH} {command}", shell=True, capture_output=True)


def update_screen_size():
    global SCREEN_W, SCREEN_H
    res = run_adb("shell wm size")
    output = res.stdout.decode('utf-8')
    if "size:" in output:
        size_str = output.split("size: ")[1].strip()
        SCREEN_W, SCREEN_H = map(int, size_str.split('x'))
        print(f"[SYSTEM] 检测到设备分辨率: {SCREEN_W}x{SCREEN_H}")


def get_ratio_pos(w_ratio, h_ratio):
    return (int(SCREEN_W * w_ratio), int(SCREEN_H * h_ratio))


def random_tap(x, y, w=20, h=20):
    if w > 0 and h > 0:
        offset_x = random.randint(-int(w * 0.2), int(w * 0.2))
        offset_y = random.randint(-int(h * 0.2), int(h * 0.2))
    else:
        offset_x, offset_y = 0, 0

    final_x, final_y = x + offset_x, y + offset_y
    print(f"  [ACTION] 👉 点击坐标: ({final_x}, {final_y})")
    run_adb(f"shell input tap {final_x} {final_y}")


def capture_screen():
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")
    return cv2.imread("screen.png")


def match_template_in_img(screen_rgb, name, template_path, threshold=0.72):
    template_rgb = cv2.imread(template_path)
    if screen_rgb is None or template_rgb is None:
        return None

    # 防误触过滤：排除底部 20%
    if name in ["reward", "action_reward", "free_listen", "dialog_close"]:
        roi_top = 0
        roi_bottom = int(SCREEN_H * 0.80)
    else:
        roi_top = 0
        roi_bottom = SCREEN_H

    screen_roi = screen_rgb[roi_top:roi_bottom, 0:SCREEN_W]
    res = cv2.matchTemplate(cv2.cvtColor(screen_roi, cv2.COLOR_BGR2GRAY),
                            cv2.cvtColor(template_rgb, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    print(f"    [🔍 扫描明细] 模板 [{name:<13}] -> 最大相似度: {max_val:.4f}")

    if max_val >= threshold:
        h, w = template_rgb.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2 + roi_top, w, h, max_val)
    return None


def wait_for_ad_finish(max_wait=70, interval=5):
    print(f"⏳ 广告播放监测中...")
    start_time = time.time()
    while (time.time() - start_time) < max_wait:
        time.sleep(interval)
        screen_img = capture_screen()
        if match_template_in_img(screen_img, "playing", TEMPLATES["playing"], threshold=0.68):
            print(f"  [STATUS] 📺 广告正在播放...")
            continue
        print("  [STATUS] ✨ 监测到画面状态发生改变，结束等待")
        return True
    return False


def main():
    print("🚀 汽水音乐纯净看广告脚本【弹窗穿透修复版】启动...")
    update_screen_size()

    COORD_CLOSE_SAFE = get_ratio_pos(0.95, 0.04)
    fail_count = 0

    while True:
        res = run_adb("shell dumpsys window | grep mCurrentFocus")
        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] App 未在前台，正在重新启动...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(8)
            fail_count = 0

        print("\n--- 正在扫描当前画面状态 ---")
        screen_img = capture_screen()

        reward_match = match_template_in_img(screen_img, "reward", TEMPLATES["reward"])
        action_match = match_template_in_img(screen_img, "action_reward", TEMPLATES["action_reward"])
        free_listen_match = match_template_in_img(screen_img, "free_listen", TEMPLATES["free_listen"])
        dialog_close_match = match_template_in_img(screen_img, "dialog_close", TEMPLATES["dialog_close"])
        success_match = match_template_in_img(screen_img, "success", TEMPLATES["success"])

        # ====== 核心判定与执行逻辑 =====

        # 状况 A：触发了任意挽留弹窗特征
        if reward_match or action_match or free_listen_match:
            print(f"  [🎯 状态] 判定结果 -> 【处理挽留/看广告弹窗】")

            # 1. 优先执行能够促使“继续看广告”的实体按钮点击
            if reward_match:
                print(f"  └─ 🎯 精准命中 [继续观看] 按钮")
                random_tap(reward_match[0], reward_match[1], w=0, h=0)
                fail_count = 0
                wait_for_ad_finish()
                continue
            elif action_match:
                print(f"  └─ 🎯 精准命中 [领取奖励] 按钮")
                random_tap(action_match[0], action_match[1], w=0, h=0)
                fail_count = 0
                wait_for_ad_finish()
                continue

            # 2. 【核心修复】：中了弹窗文字但按钮识别不到
            # 优先检查白色卡片正下方的灰色圆圈 X 号 (dialog_close)
            elif dialog_close_match:
                print(f"  └─ ⚠️ 找不到中间按钮，但精准定位到弹窗正下方的灰色关闭圆圈！")
                print("  └─ [ACTION] 🛑 精准点击弹窗自备的灰色圆圈 X 号...")
                random_tap(dialog_close_match[0], dialog_close_match[1], w=0, h=0)
                fail_count = 0
                time.sleep(4)
                continue
            # 3. 实在没有灰色圆圈，才尝试右上角的遮罩关闭（做保底）
            elif success_match:
                print(f"  └─ ⚠️ 找不到中间按钮与圆圈，尝试右上角 [领取成功x] 穿透点击...")
                exact_x = success_match[0] + 5
                exact_y = success_match[1]
                random_tap(exact_x, exact_y, w=0, h=0)
                fail_count = 0
                time.sleep(4)
                continue
            else:
                print("  └─ ⚠️ 仅通过文字判定为弹窗，且安全区内无按钮、无关闭！执行安全等待。")
                time.sleep(3)
                continue

        # 状况 B：仅“领取成功x”外层亮起，无弹窗遮挡 -> 正常的广告播放完毕
        elif success_match:
            print(f"  [🎯 状态] 仅命中 [领取成功x] (相似度: {success_match[4]:.4f}) -> 广告真正完成")
            print("  [ACTION] 🛑 正在狙击右上角关闭 X 号...")

            exact_x = success_match[0] + 5
            exact_y = success_match[1]
            random_tap(exact_x, exact_y, w=0, h=0)

            fail_count = 0
            time.sleep(4)
            continue

        # ====== 保底与异常处理 =====
        print("  [STATUS] 未识别到任何目标状态...")
        fail_count += 1

        if fail_count >= 5:
            print("  [WARNING] 连续多次未识别，尝试执行一次右上角绝对坐标保底安全关闭...")
            random_tap(COORD_CLOSE_SAFE[0], COORD_CLOSE_SAFE[1], w=0, h=0)
            fail_count = 0

        time.sleep(4)


if __name__ == "__main__":
    main()