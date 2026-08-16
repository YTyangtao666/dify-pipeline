"""L10 投放数据导入测试：CSV/JSON 双格式、字段校验、图片映射、标准结构落盘"""
import json

import pytest

from scripts.pipeline.feedback import importer as imp


class TestParseCsv:
    def test_parse_csv_with_header(self, tmp_path):
        csv = tmp_path / "r.csv"
        csv.write_text(
            "image,impressions,clicks,orders,carts\n"
            "P001_screen1_首屏定位.png,12000,360,18,90\n"
            "P001_screen2_真实痛点.png,12000,210,9,40\n",
            encoding="utf-8")
        rows = imp.parse_csv(csv)
        assert len(rows) == 2
        assert rows[0]["image"] == "P001_screen1_首屏定位.png"
        assert rows[0]["impressions"] == 12000

    def test_parse_csv_rejects_missing_columns(self, tmp_path):
        csv = tmp_path / "bad.csv"
        csv.write_text("image,clicks\na.png,10\n", encoding="utf-8")
        with pytest.raises(ValueError, match="impressions"):
            imp.parse_csv(csv)

    def test_parse_csv_rejects_bad_numbers(self, tmp_path):
        csv = tmp_path / "bad2.csv"
        csv.write_text("image,impressions,clicks,orders,carts\na.png,x,1,1,1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="数字"):
            imp.parse_csv(csv)


class TestParseJson:
    def test_parse_json_list(self, tmp_path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps([
            {"image": "a.png", "impressions": 100, "clicks": 5, "orders": 1, "carts": 3},
        ]), encoding="utf-8")
        rows = imp.parse_json(f)
        assert rows[0]["clicks"] == 5


class TestMetrics:
    def test_derived_metrics(self):
        rows = [{"image": "a.png", "impressions": 10000, "clicks": 500,
                 "orders": 20, "carts": 80}]
        enriched = imp.derive_metrics(rows)
        m = enriched[0]
        assert m["ctr"] == pytest.approx(0.05)
        assert m["cvr"] == pytest.approx(0.04)
        assert m["cart_rate"] == pytest.approx(0.008)

    def test_zero_impressions_guard(self):
        enriched = imp.derive_metrics([{"image": "a.png", "impressions": 0,
                                        "clicks": 0, "orders": 0, "carts": 0}])
        assert enriched[0]["ctr"] == 0.0  # 不除零


class TestImport:
    def test_import_writes_test_results(self, tmp_path):
        f = tmp_path / "r.csv"
        f.write_text(
            "image,impressions,clicks,orders,carts\n"
            "P001_screen1_首屏定位.png,12000,360,18,90\n",
            encoding="utf-8")
        out = imp.import_results("P001", f, out_dir=tmp_path)
        saved = json.loads((tmp_path / "test_results_P001.json").read_text(encoding="utf-8"))
        assert saved["product_id"] == "P001"
        assert saved["rows"][0]["ctr"] == pytest.approx(0.03)

    def test_import_auto_format_by_suffix(self, tmp_path):
        j = tmp_path / "r.json"
        j.write_text(json.dumps([
            {"image": "a.png", "impressions": 100, "clicks": 5, "orders": 1, "carts": 3}]),
            encoding="utf-8")
        out = imp.import_results("P1", j, out_dir=tmp_path)
        assert out["rows"][0]["impressions"] == 100

    def test_import_unknown_suffix_raises(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="格式"):
            imp.import_results("P1", f, out_dir=tmp_path)
