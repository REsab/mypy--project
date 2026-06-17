import os
import time
import subprocess
import cv2
import random
import logging
import easyocr

# 关闭日志
logging.getLogger("ppocr").setLevel(logging.ERROR)

# ================= 配置区 =================
ADB_PATH = "/Users/resab/mac/scrcpy-macos-x86_64-v3.3.1/adb"
APP_PACKAGE = "com.luna.music"
APP_ACTIVITY = "com.luna.biz.main.main.MainActivity"

IMG_DIR = "img-k80"
DIALOG_CLOSE_IMG = os.path.join(IMG_DIR, "弹窗关闭.png")

SCREEN_W = 1280
SCREEN_H = 2772

# 初始化 OCR（已替换 PaddleOCR → EasyOCR）
print("⏳ 正在加载 AI 光学字符识别引擎...")
reader = easyocr.Reader(['ch_sim', 'en'])
print("✅ OCR 引擎加载完毕！")


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


def random_tap(x, y):
    print(f"  [ACTION] 👉 精准点击坐标: ({int(x)}, {int(y)})")
    run_adb(f"shell input tap {int(x)} {int(y)}")


def capture_screen():
    run_adb("shell screencap -p /sdcard/screen.png")
    run_adb("pull /sdcard/screen.png .")
    return cv2.imread("screen.png")


def find_icon_cv2(screen_img, template_path, threshold=0.72):
    template_img = cv2.imread(template_path)
    if screen_img is None or template_img is None:
        return None

    roi_bottom = int(SCREEN_H * 0.80)
    screen_roi = screen_img[0:roi_bottom, 0:SCREEN_W]

    res = cv2.matchTemplate(
        cv2.cvtColor(screen_roi, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCOEFF_NORMED
    )

    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        h, w = template_img.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)

    return None


def analyze_screen_ocr(screen_img):
    state = {
        "is_playing": False,
        "btn_reward": None,
        "has_free_listen": False,
        "btn_success_x": None
    }

    results = reader.readtext(screen_img)

    print("    [🔍 OCR 视觉扫描结果]：")

    for box, text, score in results:
        box = [(int(p[0]), int(p[1])) for p in box]

        center_x = (box[0][0] + box[2][0]) / 2
        center_y = (box[0][1] + box[2][1]) / 2

        if center_y > SCREEN_H * 0.80:
            continue

        if score > 0.6 and any(k in text for k in ["秒", "观看", "奖励", "免费", "成功"]):
            print(f"      👀 发现文本: [{text}] (置信度: {score:.2f}) -> 坐标: y={int(center_y)}")

        if "秒后" in text or "可领取" in text:
            state["is_playing"] = True

        elif "继续观看" in text or "领取奖励" in text:
            state["btn_reward"] = (center_x, center_y)

        elif "免费听" in text:
            state["has_free_listen"] = True

        elif "领取成功" in text:
            right_edge_x = box[1][0]
            state["btn_success_x"] = (right_edge_x + 25, center_y)

    return state


def wait_for_ad_finish(max_wait=70, interval=5):
    print("⏳ 广告播放监测中...")
    start_time = time.time()

    while (time.time() - start_time) < max_wait:
        time.sleep(interval)
        screen_img = capture_screen()
        state = analyze_screen_ocr(screen_img)

        if state["is_playing"]:
            print("  [STATUS] 📺 广告正在播放...")
            continue

        print("  [STATUS] ✨ 监测到画面状态改变或出现结算，退出等待")
        return True

    return False


def main():
    print("🚀 汽水音乐自动化【EasyOCR 版本】启动...")
    update_screen_size()

    COORD_CLOSE_SAFE = get_ratio_pos(0.95, 0.04)
    fail_count = 0

    while True:
        res = run_adb("shell dumpsys window | grep mCurrentFocus")

        if APP_PACKAGE not in str(res.stdout):
            print("[SYSTEM] 重新拉起 App...")
            run_adb(f"shell am force-stop {APP_PACKAGE}")
            run_adb(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
            time.sleep(8)
            fail_count = 0

        print("\n--- 🧠 AI 正在阅读屏幕画面 ---")

        screen_img = capture_screen()
        state = analyze_screen_ocr(screen_img)

        if state["btn_reward"] or state["has_free_listen"]:
            print("  [🎯 状态] AI 判定结果 -> 【处理挽留/看广告弹窗】")

            if state["btn_reward"]:
                print("  └─ 🎯 OCR 精准定位按钮，点击！")
                random_tap(state["btn_reward"][0], state["btn_reward"][1])
                fail_count = 0
                wait_for_ad_finish()
                continue

            dialog_close_pos = find_icon_cv2(screen_img, DIALOG_CLOSE_IMG, threshold=0.70)
            if dialog_close_pos:
                print("  └─ 🛑 CV2 找到关闭按钮")
                random_tap(dialog_close_pos[0], dialog_close_pos[1])
                fail_count = 0
                time.sleep(4)
                continue

            if state["btn_success_x"]:
                print("  └─ ⚠️ 尝试关闭成功弹窗")
                random_tap(state["btn_success_x"][0], state["btn_success_x"][1])
                fail_count = 0
                time.sleep(4)
                continue

            time.sleep(3)
            continue

        elif state["btn_success_x"]:
            print("  [🎯 状态] 广告完成 -> 关闭窗口")
            random_tap(state["btn_success_x"][0], state["btn_success_x"][1])
            fail_count = 0
            time.sleep(4)
            continue

        print("  [STATUS] 未识别到关键内容...")
        fail_count += 1

        if fail_count >= 5:
            print("  [WARNING] 触发保底点击")
            random_tap(COORD_CLOSE_SAFE[0], COORD_CLOSE_SAFE[1])
            fail_count = 0

        time.sleep(4)


if __name__ == "__main__":
    main()