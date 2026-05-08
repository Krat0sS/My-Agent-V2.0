# -*- coding: utf-8 -*-
"""
My-Agent V2.0 一键启动器 — 无脑双击启动

功能：
- 自动查找 Python 3.10+
- 自动创建/修复虚拟环境
- 国内镜像加速安装依赖
- 自动安装 Playwright + Chromium
- 自动打开浏览器
- 交互式菜单
"""
import os
import sys
import subprocess
import shutil
import venv
from pathlib import Path

# ── 配置 ──
PROJECT_DIR = Path(__file__).parent.resolve()
VENV_DIR = PROJECT_DIR / "venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
ENV_FILE = PROJECT_DIR / ".env"

PREFERRED_VERSIONS = ["3.12", "3.11", "3.13", "3.10"]

PIP_MIRRORS = [
    ("https://mirrors.aliyun.com/pypi/simple/", "mirrors.aliyun.com"),
    ("https://pypi.tuna.tsinghua.edu.cn/simple/", "pypi.tuna.tsinghua.edu.cn"),
]


def banner():
    print()
    print("  ========================================")
    print("       🤖 My-Agent V2.0 启动程序")
    print("       单脑决策 · 一个入口 · 打不了架")
    print("  ========================================")
    print()


def find_python():
    """查找系统中最好的 Python"""
    for ver in PREFERRED_VERSIONS:
        try:
            r = subprocess.run(
                ["py", f"-{ver}", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                ver_str = r.stdout.strip().split()[-1] if r.stdout else ver
                print(f"  [√] Python: py -{ver} ({ver_str})")
                return ["py", f"-{ver}"], ver_str
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    for cmd in ["python", "python3"]:
        try:
            r = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                ver_str = r.stdout.strip().split()[-1]
                major, minor = int(ver_str.split(".")[0]), int(ver_str.split(".")[1])
                if major >= 3 and minor >= 10:
                    print(f"  [√] Python: {cmd} ({ver_str})")
                    return [cmd], ver_str
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None, None


def get_venv_python():
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def get_venv_pip():
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def check_venv_version(python_cmd):
    """检查 venv 的 Python 版本是否与系统匹配"""
    py = get_venv_python()
    if not py.exists():
        return False
    try:
        r = subprocess.run([str(py), "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return False
        venv_ver = r.stdout.strip().split()[-1]
        venv_major_minor = ".".join(venv_ver.split(".")[:2])
        print(f"  [i] 已有虚拟环境: Python {venv_ver}")

        r2 = subprocess.run(python_cmd + ["--version"], capture_output=True, text=True, timeout=5)
        if r2.returncode != 0:
            return True
        sys_ver = r2.stdout.strip().split()[-1]
        sys_major_minor = ".".join(sys_ver.split(".")[:2])

        if venv_major_minor != sys_major_minor:
            print(f"  [!] venv 版本 ({venv_major_minor}) 与系统 ({sys_major_minor}) 不匹配，需重建")
            return False
        return True
    except Exception:
        return False


def create_venv(python_cmd, ver_str):
    print(f"  [1/4] 创建虚拟环境 (Python {ver_str}) ...")
    try:
        venv.create(str(VENV_DIR), with_pip=True)
        print("  [√] 虚拟环境创建完成\n")
        return True
    except Exception as e:
        print(f"\n  [错误] 虚拟环境创建失败: {e}")
        return False


def upgrade_pip():
    py = get_venv_python()
    for url, host in PIP_MIRRORS:
        try:
            r = subprocess.run(
                [str(py), "-m", "pip", "install", "--upgrade", "pip",
                 "-i", url, "--trusted-host", host, "--quiet", "--no-cache-dir"],
                capture_output=True, timeout=30
            )
            if r.returncode == 0:
                return
        except (subprocess.TimeoutExpired, Exception):
            continue
    print("  [!] pip 升级跳过（网络问题，不影响使用）")


def check_deps():
    py = get_venv_python()
    try:
        r = subprocess.run(
            [str(py), "-c", "import flask, httpx, dotenv"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


def install_deps():
    py = get_venv_python()
    pip = get_venv_pip()

    print("  [2/4] 安装依赖（首次需要 1-2 分钟）...")
    print()

    for url, host in PIP_MIRRORS:
        print(f"  [i] 使用镜像: {host} ...")
        try:
            r = subprocess.run(
                [str(pip), "install", "-r", str(REQUIREMENTS),
                 "--no-cache-dir", "-i", url, "--trusted-host", host, "--timeout", "30"],
                cwd=str(PROJECT_DIR), timeout=300
            )
            if r.returncode == 0:
                print("\n  [√] 依赖安装完成")
                return True
        except subprocess.TimeoutExpired:
            print(f"\n  [!] {host} 超时，尝试下一个镜像 ...")
        except Exception as e:
            print(f"\n  [!] {host} 失败: {e}")

    print("  [i] 尝试默认源 ...")
    try:
        r = subprocess.run(
            [str(pip), "install", "-r", str(REQUIREMENTS), "--no-cache-dir"],
            cwd=str(PROJECT_DIR), timeout=300
        )
        if r.returncode == 0:
            print("  [√] 依赖安装完成")
            return True
    except Exception:
        pass

    print("\n  [错误] 依赖安装失败，请检查网络连接")
    print("  手动安装: pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/")
    return False


def fix_core_packages():
    py = get_venv_python()
    pip = get_venv_pip()

    print("  [!] 核心包导入失败，尝试重新安装 ...")
    for url, host in PIP_MIRRORS:
        try:
            subprocess.run(
                [str(pip), "install", "flask", "httpx", "python-dotenv",
                 "--no-cache-dir", "-i", url, "--trusted-host", host],
                timeout=120
            )
            break
        except Exception:
            continue

    r = subprocess.run(
        [str(py), "-c", "import flask, httpx, dotenv"],
        capture_output=True, text=True, timeout=10
    )
    if r.returncode == 0:
        print("  [√] 核心包修复成功")
        return True

    print(f"  [错误] 核心包安装失败，请手动执行:")
    print(f"    {py} -m pip install -r requirements.txt")
    return False


def check_playwright():
    py = get_venv_python()

    try:
        r = subprocess.run([str(py), "-c", "import playwright"], capture_output=True, timeout=10)
        if r.returncode == 0:
            print("  [√] Playwright 已安装")
        else:
            raise ImportError
    except (ImportError, Exception):
        print("  [3/4] 安装 Playwright ...")
        for url, host in PIP_MIRRORS:
            try:
                r = subprocess.run(
                    [str(py), "-m", "pip", "install", "playwright",
                     "-i", url, "--trusted-host", host, "--quiet", "--no-cache-dir"],
                    capture_output=True, timeout=120
                )
                if r.returncode == 0:
                    print("  [√] Playwright 安装完成")
                    break
            except Exception:
                continue
        else:
            try:
                subprocess.run(
                    [str(py), "-m", "pip", "install", "playwright", "--quiet"],
                    capture_output=True, timeout=120
                )
            except Exception:
                print("  [!] Playwright 安装失败，浏览器工具不可用")
                return False

    # 检查 Chromium
    print("  [3/4] 检查 Chromium 浏览器 ...")
    try:
        r = subprocess.run(
            [str(py), "-m", "playwright", "install", "--dry-run"],
            capture_output=True, text=True, timeout=10
        )
        if "chromium" not in r.stdout.lower() and r.returncode != 0:
            raise Exception("未安装")
        print("  [√] Chromium 浏览器已就绪")
    except Exception:
        print("  [i] 正在下载 Chromium 浏览器（首次需要几分钟）...")
        try:
            r = subprocess.run(
                [str(py), "-m", "playwright", "install", "chromium"],
                capture_output=True, timeout=300
            )
            if r.returncode == 0:
                print("  [√] Chromium 下载完成")
            else:
                print("  [!] Chromium 下载失败，首次使用浏览器工具时会自动下载")
        except subprocess.TimeoutExpired:
            print("  [!] Chromium 下载超时，请手动运行: playwright install chromium")
        except Exception as e:
            print(f"  [!] Chromium 下载失败: {e}")

    return True


def check_gitpython():
    py = get_venv_python()
    try:
        r = subprocess.run([str(py), "-c", "import git"], capture_output=True, timeout=10)
        if r.returncode == 0:
            print("  [√] GitPython 已安装 — Git 工具可用")
            return True
    except Exception:
        pass

    print("  [i] 安装 GitPython ...")
    pip = get_venv_pip()
    for url, host in PIP_MIRRORS:
        try:
            r = subprocess.run(
                [str(pip), "install", "gitpython",
                 "-i", url, "--trusted-host", host, "--quiet", "--no-cache-dir"],
                capture_output=True, timeout=60
            )
            if r.returncode == 0:
                print("  [√] GitPython 安装完成")
                return True
        except Exception:
            continue
    print("  [!] GitPython 安装失败，Git 工具不可用")
    return False


def check_pytest():
    py = get_venv_python()
    try:
        r = subprocess.run(
            [str(py), "-m", "pytest", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            ver = r.stdout.strip().split("\n")[0] if r.stdout else ""
            print(f"  [√] pytest 已安装 — {ver}")
            return True
    except Exception:
        pass

    print("  [i] 安装 pytest ...")
    pip = get_venv_pip()
    for url, host in PIP_MIRRORS:
        try:
            subprocess.run(
                [str(pip), "install", "pytest",
                 "-i", url, "--trusted-host", host, "--quiet", "--no-cache-dir"],
                capture_output=True, timeout=60
            )
            break
        except Exception:
            continue
    return True


def create_env():
    if not ENV_FILE.exists():
        print("  [√] 创建 .env 配置文件")
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("# My-Agent V2.0 配置\n")
            f.write("LLM_API_KEY=your-api-key-here\n")
            f.write("LLM_BASE_URL=https://api.deepseek.com\n")
            f.write("LLM_MODEL=deepseek-chat\n")
            f.write("\n")
            f.write("# 安全（默认开启）\n")
            f.write("SECURITY_ENABLED=true\n")
            f.write("\n")
            f.write("# 记忆\n")
            f.write("AUTO_MEMO=true\n")
            f.write("\n")
            f.write("# 技能\n")
            f.write("AUTO_SKILL_PRECIPITATE=true\n")
            f.write("SKILL_PRECIPITATE_THRESHOLD=3\n")
        print("     请在 .env 中填写 API Key，或在 Web 界面「设置」中配置")


def check_server():
    if not (PROJECT_DIR / "server.py").exists():
        print("  [错误] 未找到 server.py，请确认在正确的目录下")
        return False
    return True


def menu():
    print()
    print("  ========================================")
    print("         请选择启动模式")
    print("  ========================================")
    print("    1. 🌐 Web 界面（浏览器，推荐）")
    print("    2. 💻 命令行模式（终端交互）")
    print("    0. 退出")
    print("  ========================================")
    print()

    while True:
        try:
            choice = input("  请输入数字 (0-2): ").strip()
        except (EOFError, KeyboardInterrupt):
            return "0"
        if choice in ("1", "2", "0"):
            return choice
        print("  无效输入，请重试")


def _get_venv_env():
    """构建 venv 环境变量 — 确保子进程的 pip/python 指向 venv"""
    env = os.environ.copy()
    venv_python = str(get_venv_python())
    venv_dir = str(VENV_DIR)
    if sys.platform == "win32":
        venv_scripts = os.path.join(venv_dir, "Scripts")
    else:
        venv_scripts = os.path.join(venv_dir, "bin")
    # 设置 VIRTUAL_ENV 和 PATH，让子进程的 pip/python 指向 venv
    env["VIRTUAL_ENV"] = venv_dir
    env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
    # 确保 PYTHONPATH 不会干扰
    env.pop("PYTHONHOME", None)
    return env


def launch_web():
    py = get_venv_python()
    env = _get_venv_env()
    print()
    print("  [启动] Web 界面 ...")
    print("  地址: http://localhost:8080")
    print("  按 Ctrl+C 停止服务")
    print()
    try:
        import webbrowser
        webbrowser.open("http://localhost:8080")
    except Exception:
        pass
    r = subprocess.run([str(py), "server.py", "--port", "8080"], cwd=str(PROJECT_DIR), env=env)
    if r.returncode != 0:
        print("\n  [错误] Web 服务启动失败！")
        print("  请检查端口 8080 是否被占用")


def launch_cli():
    py = get_venv_python()
    env = _get_venv_env()
    print()
    print("  [启动] 命令行模式 ...")
    print()
    r = subprocess.run([str(py), "main.py"], cwd=str(PROJECT_DIR), env=env)
    if r.returncode != 0:
        print("\n  [错误] 命令行模式异常退出")


def main():
    banner()

    # Step 1: 找 Python
    python_cmd, ver_str = find_python()
    if not python_cmd:
        print("  [错误] 未检测到 Python 3.10+！")
        print("  请安装 Python 3.12: https://www.python.org/downloads/")
        print("  安装时请勾选 'Add Python to PATH'！")
        input("\n  按回车退出 ...")
        return

    # Step 2: 检查/创建 venv
    if VENV_DIR.exists() and check_venv_version(python_cmd):
        pass
    else:
        if VENV_DIR.exists():
            print("  [!] 虚拟环境版本不匹配，正在重建 ...")
            shutil.rmtree(str(VENV_DIR))
        if not create_venv(python_cmd, ver_str):
            input("\n  按回车退出 ...")
            return

    # Step 3: 升级 pip
    upgrade_pip()

    # Step 4: 检查/安装依赖
    if check_deps():
        print("  [2/4] 依赖已安装，跳过")
    else:
        if not install_deps():
            input("\n  按回车退出 ...")
            return

    # Step 5: 验证核心包
    if not check_deps():
        if not fix_core_packages():
            input("\n  按回车退出 ...")
            return

    # Step 6: Playwright + GitPython + pytest
    check_playwright()
    check_gitpython()
    check_pytest()

    # Step 7: .env
    create_env()

    # Step 8: 环境检查
    print()
    print("  [4/4] 环境检查 ...")
    if not check_server():
        input("\n  按回车退出 ...")
        return

    print("  [√] 环境检查通过")

    # Step 9: 菜单
    while True:
        choice = menu()
        if choice == "1":
            launch_web()
        elif choice == "2":
            launch_cli()
        elif choice == "0":
            print("  已退出")
            return

        print()
        input("  按回车返回菜单 ...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  已退出")
    except Exception as e:
        print(f"\n  [致命错误] {e}")
        import traceback
        traceback.print_exc()
        input("\n  按回车退出 ...")
