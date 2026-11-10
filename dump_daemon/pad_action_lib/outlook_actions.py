"""`Outlook.Actions`(Launch/Close/RetrieveEmailMessages/ProcessEmailMessages/
RespondToMailMessage/SaveOutlookEmailMessages/SendEmailThroughOutlook)のロジック層。

design/dsl_format_findings.md 知見208: `Microsoft.Flow.RPA.Desktop.Modules.Outlook.Actions.dll`
をdecompile(ilspycmd、クリップボード経由でVMからダウンロードしたDLLをローカルで解析——
VM側に.NET SDKが無かったため今回初採用の手法)した結果、PAD自身の実装は終始
`Activator.CreateInstance(Type.GetTypeFromProgID("Outlook.Application"))` +
リフレクション(`Type.InvokeMember`)による遅延バインドCOM操作のみで、Excel/Word/
PowerPoint(`Microsoft.Office.Interop.*`、COM専用機能のみスコープ外)と異なり
**モジュール全体がライブOutlook COM専用**(ファイルベースの代替表現が原理的に存在しない
——Outlookはファイルではなくライブなメールボックス/MAPIそのものを操作対象とするため)。
よってここでは`pywin32`の`win32com.client`による遅延バインドで1:1に近い形で再現する
(Excel/Word/PowerPointのような「ライブCOM専用機能はスコープ外」という切り捨てが
そもそも成立しない——全機能がライブCOM専用なので、COM依存を受け入れない限りOutlook
サポート自体ができない。ユーザーの明示的なスコープ拡大指示(2026-11-10、M365ライセンス
確保後)により実装する)。

**実機未確認、decompileベースの推定実装**(知見208)。他のTier3モジュールと同じ基準
(セレクタ機構が既知かつ単一の曖昧さ無しライブラリ呼び出しに対応)で安全側に倒しているが、
以下の点はdecompileのみでは完全には確定できない簡略化を含む:
- `launch_outlook()`: 実機の`LaunchOutlook`は「Explorerウィンドウが実際に表示されるまで
  最大1分ポーリングする」リトライループを持つが、これはOutlookプロセス起動直後のUI可視性
  を保証するための防御的ロジックであり、COM呼び出し自体の正しさには影響しない
  (本プロジェクトの一貫した前提である「PAD/Outlookは既にサインイン済みの状態で起動する」
  下では通常不要)。ここでは`win32com.client.Dispatch()`一発+既定フォルダのExplorer
  アクティブ化のbest-effort呼び出しのみに簡略化し、リトライループ自体は移植していない。
- `OutlookMailMessage.body_text`: 実機の`Utilities.ExtractTextFromHtml()`の正確な
  アルゴリズムは本DLL内には実装が無く(ユーティリティDLL側、別アセンブリ)未確認——
  標準ライブラリの`html.parser`でタグを除去する一般的な近似で代替した。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Sequence

from .errors import PadActionError


class LaunchOutlookError(PadActionError):
    pass


class CloseOutlookError(PadActionError):
    pass


class OutlookAccountNotFoundError(PadActionError):
    pass


class MailFolderNotFoundError(PadActionError):
    pass


class InvalidMailFolderError(PadActionError):
    pass


class ProcessEmailMessagesError(PadActionError):
    pass


class SendEmailMessageError(PadActionError):
    pass


class AttachmentNotFoundError(PadActionError):
    pass


class SaveAttachmentsDirectoryNotFoundError(PadActionError):
    pass


class RetrieveEmailMessagesError(PadActionError):
    pass


class DirectoryNotFoundError(PadActionError):
    pass


class MessageDeletedOrMovedError(PadActionError):
    pass


class SaveEmailMessagesError(PadActionError):
    pass


def _require_win32com() -> Any:
    try:
        import win32com.client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LaunchOutlookError(
            "pywin32 (win32com.client) is required to automate Outlook; this only works on Windows"
        ) from exc
    return win32com.client


class _HtmlTextExtractor(HTMLParser):
    """`OutlookMailMessage.body_text`用の簡易HTML→プレーンテキスト抽出(近似、知見208)。"""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _extract_text_from_html(html: str) -> str:
    if not html or "<" not in html:
        return html
    parser = _HtmlTextExtractor()
    parser.feed(html)
    return re.sub(r"[ \t]+", " ", parser.text()).strip()


@dataclass
class OutlookMailMessage:
    """`OutlookMailMessage`(PAD側)の1:1表現。`RetrieveEmailMessages`の出力・
    `ProcessEmailMessages`/`RespondToMailMessage`/`SaveOutlookEmailMessages`の入力として、
    実行時に不透明なレコードとして受け渡しされる(フィールドアクセス構文はまだ未確認、
    知見208)。
    """

    mail_folder: str
    entry_id: str
    sender: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    date: Any
    subject: str
    body: str
    attachments: tuple[str, ...] = field(default_factory=tuple)

    @property
    def body_text(self) -> str:
        return _extract_text_from_html(self.body)


def _as_sequence(value: OutlookMailMessage | Sequence[OutlookMailMessage]) -> list[OutlookMailMessage]:
    if isinstance(value, OutlookMailMessage):
        return [value]
    return list(value)


def _split_addresses(value: str) -> list[str]:
    return [part for part in re.split(r"[;\s]+", value.strip()) if part]


def launch_outlook() -> Any:
    win32com_client = _require_win32com()
    try:
        outlook = win32com_client.Dispatch("Outlook.Application")
        try:
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            inbox.GetExplorer().Activate()
        except Exception:
            pass  # UI可視化はbest-effort、COMインスタンス自体は既に有効(知見208)
        return outlook
    except Exception as exc:
        raise LaunchOutlookError(str(exc)) from exc


def close_outlook(outlook_instance: Any) -> None:
    if outlook_instance is None:
        return
    try:
        outlook_instance.Quit()
    except Exception as exc:
        raise CloseOutlookError(str(exc)) from exc


def _get_namespace(outlook_instance: Any) -> Any:
    namespace = outlook_instance.GetNamespace("MAPI")
    namespace.Logon()
    return namespace


def _find_store(namespace: Any, account: str) -> Any:
    for store in namespace.Stores:
        if str(store.DisplayName).casefold() == account.casefold():
            return store
    raise OutlookAccountNotFoundError(f"Outlook account '{account}' was not found")


def _find_account(namespace: Any, account: str) -> Any:
    for acct in namespace.Accounts:
        if str(acct.DisplayName).casefold() == account.casefold():
            return acct
    raise OutlookAccountNotFoundError(f"Outlook account '{account}' was not found")


def _find_folder(store: Any, folder_path: str) -> Any:
    path = folder_path.lstrip("\\")
    folder = store.GetRootFolder()
    for name in path.split("\\"):
        if not name:
            continue
        folder = _find_subfolder(folder, name)
    return folder


def _find_subfolder(folder: Any, name: str) -> Any:
    for sub in folder.Folders:
        if str(sub.Name).casefold() == name.casefold():
            return sub
    raise MailFolderNotFoundError(f"Outlook mail folder '{name}' was not found")


# design/dsl_format_findings.md 知見208: `AddressEntryUserType`の値ごとに
# SMTPアドレスの取得方法が異なる(decompile確認済み、`OutlookActions.GetEmailSmtpAddressSafe`)。
_EXCHANGE_USER_TYPES = {0, 2, 3, 4, 5}
_DISTRIBUTION_LIST_TYPE = 1
_DIRECT_ADDRESS_TYPES = {10, 11, 20, 30, 40}
_PR_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"


def _smtp_address_safe(address_entry: Any) -> str:
    if address_entry is None:
        return ""
    try:
        user_type = int(address_entry.AddressEntryUserType)
    except Exception:
        return ""
    try:
        if user_type in _EXCHANGE_USER_TYPES:
            exchange_user = address_entry.GetExchangeUser()
            if exchange_user is None:
                return ""
            return str(exchange_user.PrimarySmtpAddress or "")
        if user_type == _DISTRIBUTION_LIST_TYPE:
            dist_list = address_entry.GetExchangeDistributionList()
            if dist_list is None:
                return ""
            return str(dist_list.PrimarySmtpAddress or "")
        if user_type in _DIRECT_ADDRESS_TYPES:
            return str(address_entry.Address)
        return str(address_entry.PropertyAccessor.GetProperty(_PR_SMTP_ADDRESS))
    except Exception:
        return ""


def _recipient_email_safe(recipient: Any) -> str:
    try:
        resolved = bool(recipient.Resolve())
        address_entry = recipient.AddressEntry
        if resolved:
            return _smtp_address_safe(address_entry)
        return str(address_entry.PropertyAccessor.GetProperty(_PR_SMTP_ADDRESS))
    except Exception:
        return ""


def _sender_email_safe(mail_item: Any) -> str:
    try:
        if str(mail_item.SenderEmailType).upper() == "EX":
            sender = mail_item.Sender
            return _smtp_address_safe(sender) if sender is not None else ""
        return str(mail_item.SenderEmailAddress or "")
    except Exception:
        return ""


_RECIPIENT_TYPE_TO = 1
_RECIPIENT_TYPE_CC = 2
_RECIPIENT_TYPE_BCC = 3


def retrieve_email_messages(
    outlook_instance: Any,
    account: str,
    mail_folder: str,
    *,
    emails_to_retrieve: str = "All",
    mark_as_read: bool = True,
    read_body_as_html: bool = False,
    from_contains: str = "",
    to_contains: str = "",
    subject_contains: str = "",
    body_contains: str = "",
    attachments_options: str = "DoNotSave",
    save_attachments_into: str | None = None,
) -> list[OutlookMailMessage]:
    namespace = _get_namespace(outlook_instance)
    try:
        store = _find_store(namespace, account)
    except OutlookAccountNotFoundError:
        raise
    try:
        folder = _find_folder(store, mail_folder)
    except MailFolderNotFoundError as exc:
        raise InvalidMailFolderError(str(exc)) from exc

    items = folder.Items
    filters: list[str] = []
    if from_contains:
        filters.append(f"\"urn:schemas:httpmail:fromemail\" = '{from_contains}'")
    if body_contains:
        escaped = body_contains.replace("'", "''")
        filters.append(f"\"urn:schemas:httpmail:textdescription\" like '%{escaped}%'")
    if subject_contains:
        escaped = subject_contains.replace("'", "''")
        filters.append(f"\"urn:schemas:httpmail:subject\" like '%{escaped}%'")
    if emails_to_retrieve == "Unread":
        filters.append('"urn:schemas:httpmail:read" = 0')
    elif emails_to_retrieve == "Read":
        filters.append('"urn:schemas:httpmail:read" = 1')
    if filters:
        items = items.Restrict("@SQL= " + " AND ".join(filters))

    to_terms = _split_addresses(to_contains)
    save_into = save_attachments_into if attachments_options == "Save" else None

    results: list[OutlookMailMessage] = []
    count = items.Count
    for index in range(count, 0, -1):
        item = items.Item(index)
        try:
            body = item.HTMLBody if read_body_as_html else item.Body
        except Exception:
            body = ""
        subject = str(item.Subject or "")
        sender = _sender_email_safe(item)

        to_list: list[str] = []
        cc_list: list[str] = []
        bcc_list: list[str] = []
        try:
            recipients = item.Recipients
            for recipient in recipients:
                recipient_type = int(recipient.Type)
                address = _recipient_email_safe(recipient)
                if recipient_type == _RECIPIENT_TYPE_TO:
                    to_list.append(address)
                elif recipient_type == _RECIPIENT_TYPE_CC:
                    cc_list.append(address)
                elif recipient_type == _RECIPIENT_TYPE_BCC:
                    bcc_list.append(address)
        except Exception:
            pass

        # design/dsl_format_findings.md 知見208: `ToContains`はTo+Cc(Bccは含まない、
        # decompile確認済みの非対称仕様)の結合リストに対してマッチする。
        if to_terms and not all(any(term.casefold() in addr.casefold() for addr in to_list + cc_list) for term in to_terms):
            continue

        attachments: tuple[str, ...] = ()
        if attachments_options == "Save":
            saved: list[str] = []
            try:
                item_attachments = item.Attachments
                for attachment in item_attachments:
                    if int(attachment.Type) != 6:  # olEmbeddeditem相当は除外(decompile確認済み)
                        filename = str(attachment.FileName)
                        dest = _generate_local_file_name(save_into, filename) if save_into else filename
                        attachment.SaveAsFile(dest)
                        saved.append(dest)
            except Exception as exc:
                raise SaveAttachmentsDirectoryNotFoundError(str(exc)) from exc
            attachments = tuple(saved)

        results.append(
            OutlookMailMessage(
                mail_folder=mail_folder,
                entry_id=str(item.EntryID),
                sender=sender,
                to=tuple(to_list),
                cc=tuple(cc_list),
                bcc=tuple(bcc_list),
                date=item.ReceivedTime,
                subject=subject,
                body=str(body or ""),
                attachments=attachments,
            )
        )
        if mark_as_read:
            try:
                item.UnRead = False
            except Exception:
                pass

    return results


_PROCESS_OPERATION_TO_MOVE = "Move"


def process_email_messages(
    outlook_instance: Any,
    account: str,
    emails_to_process: OutlookMailMessage | Sequence[OutlookMailMessage],
    *,
    operation: str = "Move",
    mail_folder: str | None = None,
) -> None:
    namespace = _get_namespace(outlook_instance)
    store = _find_store(namespace, account)
    dest_folder = None
    dest_folder_name = None
    if operation == _PROCESS_OPERATION_TO_MOVE:
        if mail_folder is None:
            raise ProcessEmailMessagesError("mail_folder is required when operation='Move'")
        dest_folder = _find_folder(store, mail_folder)
        dest_folder_name = str(dest_folder.Name)

    by_folder: dict[str, list[str]] = {}
    for message in _as_sequence(emails_to_process):
        by_folder.setdefault(message.mail_folder, []).append(message.entry_id)

    store_id = store.StoreID
    try:
        for folder_name, entry_ids in by_folder.items():
            if operation == _PROCESS_OPERATION_TO_MOVE and folder_name == dest_folder_name:
                continue
            for entry_id in entry_ids:
                item = namespace.GetItemFromID(entry_id, store_id)
                if operation == "Delete":
                    item.Delete()
                elif operation == "MarkAsUnread":
                    item.UnRead = True
                elif operation == _PROCESS_OPERATION_TO_MOVE:
                    item.Move(dest_folder)
    except Exception as exc:
        raise ProcessEmailMessagesError(str(exc)) from exc


_RESPONSE_METHOD_BY_ACTION = {"Reply": "Reply", "ReplyAll": "ReplyAll", "Forward": "Forward"}


def respond_to_mail_message(
    outlook_instance: Any,
    account: str,
    mail_message: OutlookMailMessage,
    body: str,
    *,
    response_action: str = "Reply",
    send_to: str = "",
    cc: str = "",
    bcc: str = "",
    attachments: str | Sequence[str] | None = None,
) -> None:
    namespace = _get_namespace(outlook_instance)
    try:
        account_obj = _find_account(namespace, account)
    except OutlookAccountNotFoundError:
        raise

    try:
        source_item = namespace.GetItemFromID(mail_message.entry_id)
        response = getattr(source_item, _RESPONSE_METHOD_BY_ACTION[response_action])()
        response.SendUsingAccount = account_obj

        if response_action == "Forward":
            recipients = response.Recipients
            for address in _split_addresses(send_to):
                recipient = recipients.Add(address)
                recipient.Type = _RECIPIENT_TYPE_TO
                recipient.Resolve()
            for address in _split_addresses(cc):
                recipient = recipients.Add(address)
                recipient.Type = _RECIPIENT_TYPE_CC
                recipient.Resolve()
            for address in _split_addresses(bcc):
                recipient = recipients.Add(address)
                recipient.Type = _RECIPIENT_TYPE_BCC
                recipient.Resolve()

        existing_html = str(response.HTMLBody or "")
        response.HTMLBody = body.strip() + existing_html

        if attachments:
            try:
                paths = [attachments] if isinstance(attachments, str) else list(attachments)
                response_attachments = response.Attachments
                for path in paths:
                    response_attachments.Add(path)
            except Exception as exc:
                raise AttachmentNotFoundError(str(exc)) from exc

        response.Send()
    except AttachmentNotFoundError:
        raise
    except Exception as exc:
        raise SendEmailMessageError(str(exc)) from exc


_SAVE_FORMAT_TO_EXTENSION = {
    "TextOnly": ".txt",
    "OutlookTemplate": ".oft",
    "OutlookMessageFormat": ".msg",
    "OutlookMessageFormatUnicode": ".msg",
    "Html": ".html",
    "MhtFiles": ".mht",
}

# design/dsl_format_findings.md 知見208: `OlSaveAsType`(COM側の整数定数)への対応表、decompile確認済み。
_SAVE_FORMAT_TO_OL_SAVE_AS_TYPE = {
    "TextOnly": 0,
    "OutlookTemplate": 2,
    "OutlookMessageFormat": 3,
    "OutlookMessageFormatUnicode": 9,
    "Html": 5,
    "MhtFiles": 10,
}

_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name: str, replacement: str = "_") -> str:
    return _INVALID_PATH_CHARS_RE.sub(replacement, name)


def _generate_local_file_name(directory: str, filename: str) -> str:
    base = f"{directory.rstrip(chr(92)).rstrip('/')}\\{filename}"
    return base


def save_outlook_email_messages(
    outlook_instance: Any,
    account: str,
    emails_to_save: OutlookMailMessage | Sequence[OutlookMailMessage],
    save_to: str,
    *,
    save_as_mode: str = "DefaultName",
    save_as: str | None = None,
    save_format: str = "OutlookMessageFormatUnicode",
) -> list[str]:
    namespace = _get_namespace(outlook_instance)
    store = _find_store(namespace, account)

    import os

    if not os.path.isdir(save_to):
        raise DirectoryNotFoundError(f"'{save_to}' does not exist")

    extension = _SAVE_FORMAT_TO_EXTENSION[save_format]
    ol_save_as_type = _SAVE_FORMAT_TO_OL_SAVE_AS_TYPE[save_format]
    store_id = store.StoreID

    saved_paths: list[str] = []
    for message in _as_sequence(emails_to_save):
        try:
            item = namespace.GetItemFromID(message.entry_id, store_id)
        except Exception as exc:
            raise MessageDeletedOrMovedError(f"Email '{message.entry_id}' was not found") from exc

        if save_as_mode == "CustomName":
            filename = _sanitize_filename(f"{save_as}{extension}")
        else:
            seed = _sanitize_filename(str(item.Subject or ""))
            filename = _sanitize_filename(f"{seed}{extension}")
        dest = _generate_local_file_name(save_to, filename)

        try:
            item.SaveAs(dest, ol_save_as_type)
        except Exception as exc:
            raise SaveEmailMessagesError(str(exc)) from exc
        saved_paths.append(dest)

    return saved_paths


def send_email_through_outlook(
    outlook_instance: Any,
    account: str,
    send_to: str,
    subject: str,
    body: str,
    *,
    cc: str = "",
    bcc: str = "",
    attachments: str | Sequence[str] | None = None,
    is_body_html: bool = False,
    is_draft: bool = False,
    send_email_from: str = "Account",
    send_from: str | None = None,
) -> None:
    namespace = _get_namespace(outlook_instance)
    try:
        account_obj = _find_account(namespace, account)
    except OutlookAccountNotFoundError:
        raise

    try:
        mail_item = outlook_instance.CreateItem(0)
        mail_item.SendUsingAccount = account_obj

        if send_email_from == "OtherMailbox":
            if send_from is None:
                raise SendEmailMessageError("send_from is required when send_email_from='OtherMailbox'")
            mail_item.SentOnBehalfOfName = send_from

        recipients = mail_item.Recipients
        for address in _split_addresses(send_to):
            recipient = recipients.Add(address)
            recipient.Type = _RECIPIENT_TYPE_TO
            recipient.Resolve()
        for address in _split_addresses(cc):
            recipient = recipients.Add(address)
            recipient.Type = _RECIPIENT_TYPE_CC
            recipient.Resolve()
        for address in _split_addresses(bcc):
            recipient = recipients.Add(address)
            recipient.Type = _RECIPIENT_TYPE_BCC
            recipient.Resolve()

        mail_item.Subject = subject.strip()
        if is_body_html:
            mail_item.HTMLBody = body.strip()
        else:
            mail_item.Body = body.strip()

        if attachments:
            try:
                paths = [attachments] if isinstance(attachments, str) else list(attachments)
                mail_attachments = mail_item.Attachments
                for path in paths:
                    mail_attachments.Add(path)
            except Exception as exc:
                raise AttachmentNotFoundError(str(exc)) from exc

        if is_draft:
            mail_item.Save()
        else:
            mail_item.Send()
    except AttachmentNotFoundError:
        raise
    except Exception as exc:
        raise SendEmailMessageError(str(exc)) from exc
