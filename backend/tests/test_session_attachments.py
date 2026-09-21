"""Session attachment unit index, retrieval, and OCR caching."""
import pytest
from services.attachment_retrieve import (
    ATTACHMENT_CONTEXT_BUDGET,
    ensure_units,
    format_units_for_prompt,
    resolve_intent,
    select_units,
)
from services.attachment_service import (
    AttachmentService,
    MAX_ATTACHMENTS_PER_MESSAGE,
    _attachment_has_usable_text,
    set_pending_context,
)
from services.document_parser import (
    chunks_from_units,
    parse_csv,
    parse_file,
    parsed_text_from_units,
)


class _FakeSession:
    def __init__(self, pending=None):
        self.pending_context = pending or {}
        self.session_id = "sess_test"


def test_set_pending_context_preserves_attachments():
    s = _FakeSession({
        "attachments": {"att_1": {"filename": "a.pdf"}},
        "kind": "delivery",
    })
    set_pending_context(s, {})
    assert "attachments" in s.pending_context
    assert "kind" not in s.pending_context
    set_pending_context(s, {"kind": "tool_call", "approval_id": "x"})
    assert s.pending_context["kind"] == "tool_call"
    assert "att_1" in s.pending_context["attachments"]


def test_resolve_turn_unions_session_attachments():
    s = _FakeSession({
        "attachments": {
            "att_1": {"filename": "a.pdf", "uploaded_at": "2020-01-01"},
            "att_2": {"filename": "b.txt", "uploaded_at": "2020-01-02"},
        }
    })
    svc = AttachmentService()
    all_ids, new_ids = svc.resolve_turn_attachment_ids(s, ["att_2"])
    assert all_ids == ["att_1", "att_2"]
    assert new_ids == ["att_2"]


def test_resolve_turn_message_scope_only_new():
    s = _FakeSession({
        "attachments": {
            "att_1": {"filename": "a.pdf", "uploaded_at": "2020-01-01"},
            "att_2": {"filename": "b.txt", "uploaded_at": "2020-01-02"},
        }
    })
    svc = AttachmentService()
    all_ids, new_ids = svc.resolve_turn_attachment_ids(s, ["att_2"], scope="message")
    assert all_ids == ["att_2"]
    assert new_ids == ["att_2"]


def test_usable_text_and_cache_vision():
    s = _FakeSession({
        "attachments": {
            "att_1": {
                "filename": "scan.pdf",
                "parsed_text": "[扫描件] scan.pdf",
                "page_images": [{"page": 1, "stored_path": "x"}],
            }
        }
    })
    meta = s.pending_context["attachments"]["att_1"]
    assert not _attachment_has_usable_text(meta)
    AttachmentService().cache_vision_text(s, "att_1", "甲方：测试公司")
    meta = s.pending_context["attachments"]["att_1"]
    assert _attachment_has_usable_text(meta)
    units = meta.get("units") or []
    assert units and units[0]["status"] == "ready"
    assert "甲方" in units[0]["text"]


def test_ids_needing_ocr_includes_pending_even_if_new():
    s = _FakeSession({
        "attachments": {
            "att_old": {
                "filename": "old.pdf",
                "parsed_text": "[扫描件] old.pdf",
                "page_images": [{"page": 1, "stored_path": "x"}],
            },
            "att_cached": {
                "filename": "c.pdf",
                "parsed_text": "已有正文",
                "vision_text": "已有正文",
                "page_images": [{"page": 1, "stored_path": "x"}],
            },
            "att_new": {
                "filename": "n.png",
                "parsed_text": "[图片] n.png",
                "is_image": True,
                "stored_path": "x",
            },
        }
    })
    svc = AttachmentService()
    need = svc.ids_needing_vision_ocr(
        s, ["att_old", "att_cached", "att_new"], skip_ids=["att_new"]
    )
    assert "att_old" in need
    assert "att_new" in need
    assert "att_cached" not in need


def test_resolve_intent_page_semantic_full():
    assert resolve_intent("请看第3页").kind == "page"
    assert resolve_intent("请看第3页").page == 3
    assert resolve_intent("what is on page 12?").page == 12
    assert resolve_intent("总结一下这份合同").kind == "full"
    assert resolve_intent("甲方是谁？").kind == "semantic"


def test_select_units_page_lookup():
    att = {
        "filename": "doc.pdf",
        "units": [
            {"unit_index": 1, "text": "第一页内容甲方", "source": "ocr", "status": "ready"},
            {"unit_index": 2, "text": "第二页金额100万", "source": "ocr", "status": "ready"},
            {"unit_index": 3, "text": "第三页签字栏", "source": "ocr", "status": "ready"},
        ],
    }
    sel = select_units(att, "请给出第2页的内容")
    assert sel.mode == "第2页"
    assert len(sel.units) == 1
    assert sel.units[0].unit_index == 2
    assert "金额100万" in sel.units[0].text

    missing = select_units(att, "第9页写了什么")
    assert missing.mode == "页不存在"
    assert "共 3 页" in missing.message


def test_select_units_semantic_retrieval():
    att = {
        "filename": "doc.pdf",
        "units": [
            {"unit_index": 1, "text": "本合同甲方为测试科技有限公司", "source": "text_layer", "status": "ready"},
            {"unit_index": 2, "text": "交货地址为上海市浦东新区", "source": "text_layer", "status": "ready"},
            {"unit_index": 3, "text": "付款方式为银行转账", "source": "text_layer", "status": "ready"},
            {"unit_index": 4, "text": ("无关内容填充。" * 400), "source": "text_layer", "status": "ready"},
            {"unit_index": 5, "text": ("更多填充文字。" * 400), "source": "text_layer", "status": "ready"},
        ],
    }
    sel = select_units(att, "甲方是哪家公司？")
    assert sel.mode in ("相关片段", "全文")
    indices = {u.unit_index for u in sel.units}
    assert 1 in indices or any("甲方" in u.text for u in sel.units)


def test_format_units_cites_page():
    att = {
        "filename": "a.pdf",
        "units": [
            {"unit_index": 2, "text": "页二正文", "source": "ocr", "status": "ready"},
        ],
    }
    sel = select_units(att, "第2页")
    text = format_units_for_prompt("a.pdf", sel)
    assert "第2页" in text
    assert "页二正文" in text


def test_format_units_respects_char_budget():
    att = {
        "filename": "a.pdf",
        "units": [
            {"unit_index": 1, "text": "A" * 500, "source": "text_layer", "status": "ready"},
        ],
    }
    sel = select_units(att, "全文")
    text = format_units_for_prompt("a.pdf", sel, char_budget=120)
    assert "截断" in text or len(text) <= 200


def test_ensure_units_migrates_legacy_vision_text():
    att = {
        "filename": "old.pdf",
        "parsed_text": "[扫描件] old.pdf",
        "vision_text": "[第1页]\n封面标题\n\n[第2页]\n正文段落",
        "page_images": [
            {"page": 1, "stored_path": "p1.jpg"},
            {"page": 2, "stored_path": "p2.jpg"},
        ],
    }
    units = ensure_units(att)
    assert len(units) == 2
    assert units[0]["unit_index"] == 1
    assert "封面" in units[0]["text"]
    assert units[1]["unit_index"] == 2
    assert units[0].get("stored_path") == "p1.jpg"


def test_ensure_units_pending_from_page_images():
    att = {
        "filename": "scan.pdf",
        "parsed_text": "[扫描件] scan.pdf",
        "page_images": [
            {"page": 1, "stored_path": "a.jpg", "mime_type": "image/jpeg"},
            {"page": 2, "stored_path": "b.jpg", "mime_type": "image/jpeg"},
        ],
    }
    units = ensure_units(att)
    assert len(units) == 2
    assert all(u["status"] == "pending" for u in units)


def test_cache_unit_text_preserves_other_pages():
    s = _FakeSession({
        "attachments": {
            "att_1": {
                "filename": "m.pdf",
                "units": [
                    {"unit_index": 1, "text": "页一", "source": "ocr", "status": "ready"},
                    {
                        "unit_index": 2,
                        "text": "",
                        "source": "ocr",
                        "status": "pending",
                        "stored_path": "p2.jpg",
                    },
                ],
                "parsed_text": "[第1页]\n页一",
                "chunks": ["[p.1] 页一"],
            }
        }
    })
    AttachmentService().cache_unit_text(s, "att_1", 2, "页二OCR结果", vision_model="vl-test")
    meta = s.pending_context["attachments"]["att_1"]
    units = meta["units"]
    assert units[0]["text"] == "页一"
    assert units[1]["text"] == "页二OCR结果"
    assert units[1]["status"] == "ready"
    assert "[p.2]" in " ".join(meta.get("chunks") or [])


def test_chunks_from_units_prefix():
    units = [
        {"unit_index": 3, "text": "hello world paragraph", "status": "ready"},
    ]
    chunks = chunks_from_units(units)
    assert chunks
    assert chunks[0].startswith("[p.3]")


def test_parsed_text_from_units_multi_page():
    units = [
        {"unit_index": 1, "text": "A", "status": "ready"},
        {"unit_index": 2, "text": "B", "status": "ready"},
    ]
    text = parsed_text_from_units(units, "x.pdf")
    assert "[第1页]" in text
    assert "[第2页]" in text


def test_build_context_page_query():
    s = _FakeSession({
        "attachments": {
            "att_1": {
                "filename": "contract.pdf",
                "units": [
                    {"unit_index": 1, "text": "封面", "source": "text_layer", "status": "ready"},
                    {"unit_index": 2, "text": "条款二详细内容", "source": "text_layer", "status": "ready"},
                ],
                "parsed_text": "封面\n\n条款二",
                "chunks": ["[p.1] 封面", "[p.2] 条款二详细内容"],
                "is_image": False,
                "page_images": [],
            }
        }
    })
    svc = AttachmentService()
    suffix, images, meta = svc.build_context(
        s, "请告诉我第2页写了什么", ["att_1"], history=[],
        model_capabilities=["text"],
    )
    assert "第2页" in suffix
    assert "条款二详细内容" in suffix
    assert meta[0]["filename"] == "contract.pdf"
    assert images is None


def test_build_context_inventory_for_multi_attachments():
    s = _FakeSession({
        "attachments": {
            "att_1": {
                "filename": "a.pdf",
                "units": [{"unit_index": 1, "text": "AAA", "status": "ready", "source": "text_layer"}],
                "parsed_text": "AAA",
                "chunks": ["[p.1] AAA"],
            },
            "att_2": {
                "filename": "b.pdf",
                "units": [{"unit_index": 1, "text": "BBB", "status": "ready", "source": "text_layer"}],
                "parsed_text": "BBB",
                "chunks": ["[p.1] BBB"],
            },
        }
    })
    suffix, _, _ = AttachmentService().build_context(
        s, "对比两份文件", ["att_1", "att_2"], history=[],
        model_capabilities=["text"],
    )
    assert "会话附件清单" in suffix
    assert "a.pdf" in suffix and "b.pdf" in suffix
    assert ATTACHMENT_CONTEXT_BUDGET >= 1000


def test_parse_pdf_units_mixed_pages(monkeypatch):
    from services import document_parser as dp

    class _FakePage:
        def __init__(self, text, has_image=False):
            self._text = text
            self._has_image = has_image
            self.images = []

        def extract_text(self):
            return self._text

    class _FakeReader:
        def __init__(self, *_a, **_k):
            self.pages = [
                _FakePage("这是一段足够长的文字层内容，超过三十个字符用来通过阈值。" * 1),
                _FakePage("", has_image=True),
            ]

    def fake_embedded(page):
        if getattr(page, "_has_image", False) or not (page.extract_text() or "").strip():
            return b"fakeimg", ".jpg", "image/jpeg"
        return None

    import PyPDF2
    monkeypatch.setattr(PyPDF2, "PdfReader", _FakeReader)
    monkeypatch.setattr(dp, "_extract_embedded_page_image", fake_embedded)
    monkeypatch.setattr(dp, "_render_page_with_pypdfium2", lambda *_a, **_k: None)

    units = dp.parse_pdf_units(b"%PDF-fake")
    assert len(units) == 2
    assert units[0]["status"] == "ready"
    assert units[1]["status"] == "pending"
    assert units[1].get("_image_bytes") == b"fakeimg"


def test_parse_csv_and_reject_doc():
    text = parse_csv("a,b\n1,2\n".encode("utf-8"))
    assert "a,b" in text
    with pytest.raises(ValueError, match="docx"):
        parse_file(b"not-a-real-doc", "legacy.doc")


def test_message_attachment_limit_constant():
    assert MAX_ATTACHMENTS_PER_MESSAGE == 5


def test_product_version_is_1_06():
    from version import __version__
    assert __version__ == "1.06"


def test_flatten_user_content_text_and_images():
    assert AttachmentService.flatten_user_content("hello") == "hello"
    assert AttachmentService.flatten_user_content(None) == ""
    flat = AttachmentService.flatten_user_content([
        {"type": "text", "text": "请看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
        {"type": "text", "text": "第二段"},
    ])
    assert "请看图" in flat
    assert "[图像附件]" in flat
    assert "第二段" in flat


@pytest.mark.asyncio
async def test_prepare_text_only_injects_parsed_attachment():
    from types import SimpleNamespace
    from services.agent_service import AgentService

    s = _FakeSession({
        "attachments": {
            "att_1": {
                "filename": "policy.txt",
                "parsed_text": "差旅报销需提供发票",
                "units": [{
                    "unit_index": 1,
                    "text": "差旅报销需提供发票",
                    "status": "ready",
                    "source": "parse",
                }],
            }
        }
    })
    s.messages = []
    provider = SimpleNamespace(provider_id="p1", provider_code="p")
    model_svc = SimpleNamespace(
        capabilities=["text"],
        model_name="deepseek-chat",
        model_service_id="ms-1",
    )
    prep = await AgentService._prepare_attachment_turn(
        db=None,
        session=s,
        message="根据附件检查",
        attachment_ids=["att_1"],
        attachment_scope="session",
        provider=provider,
        model_svc=model_svc,
        text_only=True,
    )
    assert prep["original_message"] == "根据附件检查"
    assert "差旅报销" in prep["prepared_message"]
    assert isinstance(prep["prepared_message"], str)
    assert prep["attachment_metadata"][0]["filename"] == "policy.txt"
    assert "暂不支持附件解析" not in prep["prepared_message"]


@pytest.mark.asyncio
async def test_finalize_workflow_persists_original_not_injected():
    from unittest.mock import MagicMock
    from services.agent_service import AgentService

    session = MagicMock()
    session.messages = []
    session.token_used = 0
    session.pending_context = {}
    session.status = None
    db = MagicMock()
    result = {
        "status": "completed",
        "result": "已根据发票完成核对",
        "total_tokens": 3,
        "thinking_log": [],
        "execution_trace": [],
        "trace": [],
    }
    out = await AgentService._finalize_workflow_chat(
        db,
        session,
        "INJECTED HUGE TEXT with 差旅政策全文",
        result,
        persist_user_message=True,
        original_message="请看附件",
        attachment_metadata=[{"id": "att_1", "filename": "a.pdf"}],
    )
    user = session.messages[0]
    assert user["content"] == "请看附件"
    assert user["attachments"][0]["filename"] == "a.pdf"
    assert session.messages[1]["content"] == "已根据发票完成核对"
    assert out["execution_mode"] == "workflow"
