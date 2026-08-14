"""videogen 模块测试：TTS 生成 + FFmpeg 命令构建 + 合成流程"""
import pytest

from scripts.pipeline import videogen


class TestTts:
    async def test_tts_writes_mp3(self, tmp_path, monkeypatch):
        """edge_tts 合成 → 落盘 mp3（mock edge_tts）"""
        class FakeCommunicate:
            def __init__(self, text, voice):
                self.text, self.voice = text, voice

            async def save(self, path):
                with open(path, "wb") as f:
                    f.write(b"ID3fake-mp3")

        class FakeEdgeTTS:
            def __init__(self):
                self.last_args = None

            def Communicate(self, text, voice):
                self.last_args = (text, voice)
                return FakeCommunicate(text, voice)

        fake = FakeEdgeTTS()
        import sys
        monkeypatch.setitem(sys.modules, "edge_tts", fake)
        monkeypatch.setattr(videogen, "probe_duration", lambda p: 5.0)

        out = tmp_path / "t.mp3"
        await videogen.tts_to_mp3("大家好", voice="zh-CN-X", out_path=out)

        assert out.read_bytes() == b"ID3fake-mp3"
        assert fake.last_args == ("大家好", "zh-CN-X")


class TestFfmpegCmd:
    def test_build_ffmpeg_cmd_basic(self, tmp_path):
        """3 张图 + 1 段音频 → ffmpeg 轮播合成命令"""
        imgs = [tmp_path / f"{i}.png" for i in range(3)]
        audio = tmp_path / "a.mp3"
        out = tmp_path / "v.mp4"

        cmd = videogen.build_ffmpeg_cmd(imgs, audio, out, per_image_sec=4)

        joined = " ".join(cmd)
        assert "concat" in joined
        assert str(out) in joined
        assert str(audio) in joined
        # 每张图都被引用
        for img in imgs:
            assert str(img) in joined

    def test_audio_duration_probing(self, tmp_path):
        """ffprobe 获取音频时长（mock subprocess）"""
        import subprocess as sp

        def fake_run(cmd, **kw):
            assert "ffprobe" in cmd[0]
            return sp.CompletedProcess(cmd, 0, stdout="12.5\n", stderr="")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(sp, "run", fake_run)
        try:
            assert videogen.probe_duration(tmp_path / "a.mp3") == 12.5
        finally:
            monkeypatch.undo()


class TestCompose:
    async def test_compose_video_pipeline(self, tmp_path, monkeypatch):
        """端到端合成：TTS → 时长探测 → ffmpeg（全部 mock）"""
        import subprocess as sp

        # 准备假图片
        for i in range(2):
            (tmp_path / f"{i}.png").write_bytes(b"\x89PNG")

        events = []

        async def fake_tts(text, voice, out_path):
            events.append(("tts", text))
            out_path.write_bytes(b"mp3")
            return 10.0  # 假时长

        def fake_run(cmd, **kw):
            events.append(("ffmpeg", cmd[0]))
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(videogen, "tts_to_mp3", fake_tts)
        monkeypatch.setattr(sp, "run", fake_run)
        monkeypatch.setattr(videogen, "probe_duration", lambda p: 10.0)

        product = {"product_id": "P1", "title": "保温杯", "desc": "316不锈钢"}
        images = [tmp_path / "0.png", tmp_path / "1.png"]

        video_path = await videogen.compose_video(
            images, tts_text="口播文案", voice="zh-CN-X",
            out_path=tmp_path / "out.mp4", per_image_sec=5)

        assert ("tts", "口播文案") in events
        assert any(e[0] == "ffmpeg" for e in events)
        assert video_path == tmp_path / "out.mp4"
