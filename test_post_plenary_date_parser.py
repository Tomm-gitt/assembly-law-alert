from post_plenary import _find_date


def main():
    cases = [
        ("정부이송일 2026. 2. 27.", "정부이송일", "2026-02-27"),
        ("공포일자\n2026. 3. 10.", "공포일자", "2026-03-10"),
        ("공포일자 2026-03-10", "공포일자", "2026-03-10"),
        ("공포일자 2026년 3월 10일", "공포일자", "2026-03-10"),
    ]
    for text, label, expected in cases:
        actual = _find_date(text, label)
        if actual != expected:
            raise AssertionError(f"{label}: actual={actual!r}, expected={expected!r}, text={text!r}")
        print(f"[PASS] {label}: {text!r} -> {actual}")


if __name__ == "__main__":
    main()
