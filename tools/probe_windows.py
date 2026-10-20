import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]

GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetClassNameW = user32.GetClassNameW
IsWindowVisible = user32.IsWindowVisible
GetWindowThreadProcessId = user32.GetWindowThreadProcessId

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
OpenProcess = kernel32.OpenProcess
QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
CloseHandle = kernel32.CloseHandle


def proc_name(pid):
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    ok = QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    CloseHandle(h)
    return buf.value if ok else ""


rows = []


def cb(hwnd, lparam):
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pn = proc_name(pid.value)
    if "weixin" in pn.lower() or "wechat" in pn.lower():
        n = GetWindowTextLengthW(hwnd)
        tbuf = ctypes.create_unicode_buffer(n + 2)
        GetWindowTextW(hwnd, tbuf, n + 2)
        cbuf = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cbuf, 256)
        rows.append((hwnd, pid.value, cbuf.value, tbuf.value, bool(IsWindowVisible(hwnd)), pn))
    return True


EnumWindows(EnumWindowsProc(cb), 0)

print(f"matched {len(rows)} windows")
for r in rows:
    print(f"hwnd=0x{r[0]:X} pid={r[1]} visible={r[4]} class=[{r[2]}] title=[{r[3]}]")
    print(f"    exe={r[5]}")
