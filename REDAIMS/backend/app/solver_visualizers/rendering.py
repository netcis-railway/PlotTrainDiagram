import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import ROOT
from app.solver_visualizers.configuration import ConfigurationError, decode_log


def render_plot(content, filename, encoding, plotter, options):
    if not plotter.available():
        raise ConfigurationError("配置的作图脚本不存在，请检查solver_visualizers目录")
    text = decode_log(content, encoding)
    with TemporaryDirectory(prefix="redaims-solver-") as directory:
        root = Path(directory).resolve()
        source = root / "input.log"
        source.write_text(text, encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            MPLBACKEND="Agg",
            MPLCONFIGDIR=str(root / "mpl"),
            PYTHONIOENCODING="utf-8",
            PYTHONPATH=str(ROOT / "backend"),
        )
        payload = {
            "module": plotter.module,
            "function": plotter.function,
            "input_path": str(source),
            "output_dir": directory,
            "filename": filename,
            "options": options,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "app.solver_visualizers.worker"],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                cwd=root,
                timeout=plotter.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("日志作图超时，请缩小日志范围或检查作图函数") from error
        if result.returncode:
            raise ConfigurationError("日志作图进程启动失败，请检查后端Python依赖")
        try:
            answer = json.loads(result.stdout)
        except ValueError as error:
            raise ConfigurationError("作图函数未返回有效结果") from error
        if not answer.get("ok"):
            if "No module named" in answer.get("error", ""):
                raise ConfigurationError("作图依赖缺失：" + answer["error"])
            raise ValueError("日志作图失败：" + answer.get("error", "未知错误"))
        image = Path(answer["image_path"]).resolve()
        if not image.is_relative_to(root) or image.suffix.lower() != ".png" or not image.is_file():
            raise ConfigurationError("作图函数须返回临时输出目录内的PNG文件")
        if image.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("生成的图片超过16MB")
        content = image.read_bytes()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ConfigurationError("作图函数没有生成有效PNG文件")
        return {
            "plotter_id": plotter.id,
            "label": plotter.label,
            "mime_type": "image/png",
            "image_base64": base64.b64encode(content).decode("ascii"),
            "summary": answer.get("summary", {}),
            "image_name": Path(filename).stem + "_progress.png",
        }
