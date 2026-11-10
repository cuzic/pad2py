"""`dump_daemon.pad_action_lib.outlook_actions`の単体テスト。

design/dsl_format_findings.md 知見208: このモジュール全体がライブOutlook COM専用
(`win32com.client`経由)のため、このLinux環境では実際のOutlookに対する統合テストは
書けない——`services_actions`の既存テスト(`monkeypatch.setitem(sys.modules, ...)`で
`win32serviceutil`相当を偽装する手法)を踏襲し、COM呼び出しに依存しない純粋なヘルパー
関数と、`win32com`自体が無い場合のフォールバック挙動を確認する。`send_email_through_outlook`
のみ、COM呼び出し列(`Recipients.Add`/`Resolve`/`Send`)を記録する最小限の偽オブジェクト
グラフで検証する——`retrieve_email_messages`等のより複雑なCOM走査(`Items.Restrict`・
`Recipients`の`Type`分岐・`PropertyAccessor`のSMTPアドレス解決)は、実機未確認のロジックを
不正確な偽COMで「検証済み」と誤認させるリスクが高いため、今回はVM実機確認を待つ
(でっち上げた検証を作らない方針)。
"""
from __future__ import annotations

import builtins

import pytest

from dump_daemon.pad_action_lib import outlook_actions as oa


def test_extract_text_from_html_strips_tags_and_collapses_whitespace() -> None:
    html = "<html><body><p>Hello,  <b>world</b>!</p></body></html>"
    assert oa._extract_text_from_html(html) == "Hello, world!"


def test_extract_text_from_html_passes_through_plain_text_unchanged() -> None:
    assert oa._extract_text_from_html("no html here") == "no html here"


def test_outlook_mail_message_body_text_property_uses_html_extraction() -> None:
    message = oa.OutlookMailMessage(
        mail_folder="Inbox",
        entry_id="abc",
        sender="a@example.com",
        to=("b@example.com",),
        cc=(),
        bcc=(),
        date=None,
        subject="Hi",
        body="<p>Hello <b>world</b></p>",
    )
    assert message.body_text == "Hello world"


def test_split_addresses_handles_semicolon_and_whitespace_separators() -> None:
    assert oa._split_addresses("a@example.com; b@example.com ;; c@example.com") == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


def test_split_addresses_empty_string_returns_empty_list() -> None:
    assert oa._split_addresses("") == []
    assert oa._split_addresses("   ") == []


def test_sanitize_filename_replaces_invalid_path_characters() -> None:
    assert oa._sanitize_filename('a:b/c\\d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_generate_local_file_name_joins_with_backslash() -> None:
    assert oa._generate_local_file_name("C:\\out", "msg.msg") == "C:\\out\\msg.msg"
    assert oa._generate_local_file_name("C:\\out\\", "msg.msg") == "C:\\out\\msg.msg"


def test_as_sequence_wraps_single_message_and_passes_through_list() -> None:
    message = oa.OutlookMailMessage(
        mail_folder="Inbox",
        entry_id="1",
        sender="a@example.com",
        to=(),
        cc=(),
        bcc=(),
        date=None,
        subject="",
        body="",
    )
    assert oa._as_sequence(message) == [message]
    assert oa._as_sequence([message, message]) == [message, message]


def test_launch_outlook_raises_when_pywin32_is_unavailable() -> None:
    real_import = builtins.__import__

    def _blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "win32com.client" or name.startswith("win32com"):
            raise ImportError("no pywin32 on this platform")
        return real_import(name, *args, **kwargs)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(builtins, "__import__", _blocked_import)
        with pytest.raises(oa.LaunchOutlookError):
            oa.launch_outlook()


class _FakeRecipient:
    def __init__(self, address: str, recipient_type: int) -> None:
        self.address = address
        self.Type = recipient_type
        self.resolved = False

    def Resolve(self) -> bool:
        self.resolved = True
        return True


class _FakeRecipients(list):
    def Add(self, address: str) -> _FakeRecipient:
        recipient = _FakeRecipient(address, 0)
        self.append(recipient)
        return recipient


class _FakeAttachments(list):
    def Add(self, path: str) -> None:
        self.append(path)


class _FakeMailItem:
    def __init__(self) -> None:
        self.Recipients = _FakeRecipients()
        self.Attachments = _FakeAttachments()
        self.SendUsingAccount = None
        self.Subject = None
        self.Body = None
        self.HTMLBody = None
        self.sent = False
        self.saved = False

    def Send(self) -> None:
        self.sent = True

    def Save(self) -> None:
        self.saved = True


class _FakeAccount:
    def __init__(self, display_name: str) -> None:
        self.DisplayName = display_name


class _FakeNamespace:
    def __init__(self, accounts: list[_FakeAccount]) -> None:
        self.Accounts = accounts
        self.logged_on = False

    def Logon(self) -> None:
        self.logged_on = True


class _FakeOutlookApplication:
    def __init__(self, namespace: _FakeNamespace, mail_item: _FakeMailItem) -> None:
        self._namespace = namespace
        self._mail_item = mail_item
        self.created_item_types: list[int] = []

    def GetNamespace(self, kind: str) -> _FakeNamespace:
        assert kind == "MAPI"
        return self._namespace

    def CreateItem(self, item_type: int) -> _FakeMailItem:
        self.created_item_types.append(item_type)
        return self._mail_item


def test_send_email_through_outlook_resolves_recipients_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _FakeAccount("tomoya@example.com")
    namespace = _FakeNamespace([account])
    mail_item = _FakeMailItem()
    app = _FakeOutlookApplication(namespace, mail_item)

    oa.send_email_through_outlook(
        app,
        "tomoya@example.com",
        "a@example.com; b@example.com",
        "Subject here",
        "Body here",
        cc="c@example.com",
    )

    assert namespace.logged_on
    assert mail_item.SendUsingAccount is account
    assert mail_item.Subject == "Subject here"
    assert mail_item.Body == "Body here"
    assert [r.address for r in mail_item.Recipients if r.Type == oa._RECIPIENT_TYPE_TO] == [
        "a@example.com",
        "b@example.com",
    ]
    assert [r.address for r in mail_item.Recipients if r.Type == oa._RECIPIENT_TYPE_CC] == ["c@example.com"]
    assert all(r.resolved for r in mail_item.Recipients)
    assert mail_item.sent
    assert not mail_item.saved


def test_send_email_through_outlook_is_draft_saves_instead_of_sending() -> None:
    account = _FakeAccount("tomoya@example.com")
    namespace = _FakeNamespace([account])
    mail_item = _FakeMailItem()
    app = _FakeOutlookApplication(namespace, mail_item)

    oa.send_email_through_outlook(
        app, "tomoya@example.com", "a@example.com", "s", "b", is_draft=True
    )

    assert mail_item.saved
    assert not mail_item.sent


def test_send_email_through_outlook_unknown_account_raises() -> None:
    namespace = _FakeNamespace([_FakeAccount("other@example.com")])
    mail_item = _FakeMailItem()
    app = _FakeOutlookApplication(namespace, mail_item)

    with pytest.raises(oa.OutlookAccountNotFoundError):
        oa.send_email_through_outlook(app, "tomoya@example.com", "a@example.com", "s", "b")


def test_send_email_through_outlook_html_body_sets_htmlbody_field() -> None:
    account = _FakeAccount("tomoya@example.com")
    namespace = _FakeNamespace([account])
    mail_item = _FakeMailItem()
    app = _FakeOutlookApplication(namespace, mail_item)

    oa.send_email_through_outlook(
        app, "tomoya@example.com", "a@example.com", "s", "<b>hi</b>", is_body_html=True
    )

    assert mail_item.HTMLBody == "<b>hi</b>"
    assert mail_item.Body is None
