"""`Outlook.*`のcodegen。

`pad_action_lib.outlook_actions`へ委譲する。design/dsl_format_findings.md 知見208:
`Microsoft.Flow.RPA.Desktop.Modules.Outlook.Actions.dll`をdecompile(本モジュール初採用の
「VMからクリップボード経由でDLLをダウンロードし、ローカルの.NET SDK+ilspycmdで解析する」
手法——VM側に.NET SDKが無かったため)した結果、`[Action]`クラスは7系統:

- `CloseOutlook`(`[Action(Name = "Close")]`)/`LaunchOutlook`(`[Action(Name = "Launch")]`)の
  2件はフラットな2セグメント形式(`Outlook.Close`/`Outlook.Launch`)。
- 残り5件は`[Action(Order = N)]`のみ(`Id`/`Name`属性無し)で、`ActionSelectorBase`派生の
  兄弟セレクタを持つ——他の全モジュール(Excel/Word/PowerPoint/PDF、知見155-158)と同じ
  `tools/pad_selector_audit.py`の既定仮定(`Id`属性の上書きが無ければクラス名そのものが
  中間セグメント)通り、3セグメント形式`Outlook.<クラス名>.<UseName()の値>`になる
  (`ProcessEmailMessages`/`RespondToMailMessage`/`RetrieveEmailMessages`/
  `SaveOutlookEmailMessages`/`SendEmailThroughOutlook`)。第3セグメントは各
  `ActionSelector<T>`サブクラスの`UseName(...)`呼び出しそのもの(decompileソースを直接
  読んだ値、推測ではない)。

Excel/Word/PowerPoint(`Microsoft.Office.Interop.*`、ライブCOM専用機能だけがスコープ外)と
異なり、Outlookは**モジュール全体がライブOutlook COM専用**(メールボックスはファイルでは
ないため、file-basedな代替表現が原理的に存在しない)。`pad_action_lib.outlook_actions`
全体が`win32com.client`経由の遅延バインドCOM操作であり、実機未確認・decompileベースの
推定実装である点は各関数のdocstringに明記済み。

`Instance`(`OutlookInstanceHandle`への参照)は他モジュールの`Instance`と同じく、PAD側では
不透明な参照だがPythonコード生成の観点では他の変数参照と同じ(特別な結線は不要)。

`EmailsToProcess`/`EmailsToSave`/`Attachments`は、decompileで確認した「単一要素なら
生の値、複数要素なら`{...}`配列リテラル」という曖昧さを`compression.py`の
`_as_list_expr()`と同じ方式で吸収する。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def _as_list_expr(rendered: str) -> str:
    return f"({rendered} if isinstance({rendered}, list) else [{rendered}])"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Outlook."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Outlook.Launch":
        if not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = outlook_actions.launch_outlook()"]

    if action_id == "Outlook.Close":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [f"{prefix}outlook_actions.close_outlook({instance})"]

    # 知見208: `ProcessEmailMessages`の兄弟セレクタ3件(`Operation`は`Delete`/`Move`/
    # `MarkAsUnread`で固定、`DeleteEmails`/`MarkEmailsAsUnread`は`MailFolder`が
    # `Hide<>()`されている=常に無関係)。
    _PROCESS_OPERATION_BY_ACTION = {
        "Outlook.ProcessEmailMessages.DeleteEmails": "Delete",
        "Outlook.ProcessEmailMessages.MarkEmailsAsUnread": "MarkAsUnread",
        "Outlook.ProcessEmailMessages.MoveEmails": "Move",
    }
    operation = _PROCESS_OPERATION_BY_ACTION.get(action_id)
    if operation is not None:
        instance = safe_render(p.get("Instance"))
        account = safe_render(p.get("Account"))
        emails = safe_render(p.get("EmailsToProcess"))
        if instance is None or account is None or emails is None:
            return None
        if operation == "Move":
            mail_folder = safe_render(p.get("MailFolder"))
            if mail_folder is None:
                return None
            return [
                f"{prefix}outlook_actions.process_email_messages({instance}, {account}, "
                f"{_as_list_expr(emails)}, operation={operation!r}, mail_folder={mail_folder})"
            ]
        return [
            f"{prefix}outlook_actions.process_email_messages({instance}, {account}, "
            f"{_as_list_expr(emails)}, operation={operation!r})"
        ]

    # 知見208: `RespondToMailMessage`の兄弟セレクタ3件(`ResponseAction`は`Reply`/
    # `ReplyAll`/`Forward`で固定、`ReplyToEmail`/`ReplyAllToEmail`は`SendTo`/`CC`/`BCC`が
    # 全て`Hide<>()`されている=元の送信者へ返信するだけで宛先指定が無関係)。
    _RESPONSE_ACTION_BY_ACTION = {
        "Outlook.RespondToMailMessage.ReplyToEmail": "Reply",
        "Outlook.RespondToMailMessage.ReplyAllToEmail": "ReplyAll",
        "Outlook.RespondToMailMessage.ForwardEmail": "Forward",
    }
    response_action = _RESPONSE_ACTION_BY_ACTION.get(action_id)
    if response_action is not None:
        instance = safe_render(p.get("Instance"))
        account = safe_render(p.get("Account"))
        mail_message = safe_render(p.get("MailMessage"))
        body = safe_render(p.get("Body", ""))
        if None in (instance, account, mail_message, body):
            return None
        extra = ""
        if response_action == "Forward":
            send_to = safe_render(p.get("SendTo"))
            cc = safe_render(p.get("CC", ""))
            bcc = safe_render(p.get("BCC", ""))
            if None in (send_to, cc, bcc):
                return None
            extra = f", send_to={send_to}, cc={cc}, bcc={bcc}"
        attachments = p.get("Attachments")
        attachments_rendered = safe_render(attachments) if attachments else repr(None)
        if attachments_rendered is None:
            return None
        attachments_expr = _as_list_expr(attachments_rendered) if attachments else "None"
        return [
            f"{prefix}outlook_actions.respond_to_mail_message({instance}, {account}, "
            f"{mail_message}, {body}, response_action={response_action!r}{extra}, "
            f"attachments={attachments_expr})"
        ]

    # 知見208: `RetrieveEmailMessages`の兄弟セレクタ2件(`AttachmentsOptions`は`DoNotSave`/
    # `Save`で固定、`RetrieveEmails`は`SaveAttachmentsInto`が`Hide<>()`されている)。
    _RETRIEVE_ATTACHMENTS_OPTIONS_BY_ACTION = {
        "Outlook.RetrieveEmailMessages.RetrieveEmails": "DoNotSave",
        "Outlook.RetrieveEmailMessages.RetrieveEmailsAndSaveAttachments": "Save",
    }
    attachments_options = _RETRIEVE_ATTACHMENTS_OPTIONS_BY_ACTION.get(action_id)
    if attachments_options is not None:
        instance = safe_render(p.get("Instance"))
        account = safe_render(p.get("Account"))
        mail_folder = safe_render(p.get("MailFolder"))
        emails_to_retrieve = _enum_mode(p.get("EmailsToRetrieve"), default="All")
        mark_as_read = safe_render(p.get("MarkAsRead", True))
        read_body_as_html = safe_render(p.get("ReadBodyAsHtml", False))
        from_contains = safe_render(p.get("FromContains", ""))
        to_contains = safe_render(p.get("ToContains", ""))
        subject_contains = safe_render(p.get("SubjectContains", ""))
        body_contains = safe_render(p.get("BodyContains", ""))
        if None in (
            instance,
            account,
            mail_folder,
            emails_to_retrieve,
            mark_as_read,
            read_body_as_html,
            from_contains,
            to_contains,
            subject_contains,
            body_contains,
        ) or not node.output_var:
            return None
        extra = ""
        if attachments_options == "Save":
            save_into = safe_render(p.get("SaveAttachmentsInto"))
            if save_into is None:
                return None
            extra = f", save_attachments_into={save_into}"
        return [
            f"{prefix}{node.output_var} = outlook_actions.retrieve_email_messages({instance}, "
            f"{account}, {mail_folder}, emails_to_retrieve={emails_to_retrieve!r}, "
            f"mark_as_read={mark_as_read}, read_body_as_html={read_body_as_html}, "
            f"from_contains={from_contains}, to_contains={to_contains}, "
            f"subject_contains={subject_contains}, body_contains={body_contains}, "
            f"attachments_options={attachments_options!r}{extra})"
        ]

    # 知見208: `SaveOutlookEmailMessages`の兄弟セレクタ2件(`SaveAsMode`は`DefaultName`/
    # `CustomName`で固定、`SaveEmails`は`SaveEmailsAs`が`Hide<>()`されている)。
    _SAVE_AS_MODE_BY_ACTION = {
        "Outlook.SaveOutlookEmailMessages.SaveEmails": "DefaultName",
        "Outlook.SaveOutlookEmailMessages.SaveEmailsAs": "CustomName",
    }
    save_as_mode = _SAVE_AS_MODE_BY_ACTION.get(action_id)
    if save_as_mode is not None:
        instance = safe_render(p.get("Instance"))
        account = safe_render(p.get("Account"))
        emails = safe_render(p.get("EmailsToSave"))
        save_to = safe_render(p.get("SaveEmailsTo"))
        save_format = _enum_mode(p.get("SaveFormat"), default="OutlookMessageFormatUnicode")
        if None in (instance, account, emails, save_to, save_format) or not node.output_var:
            return None
        extra = ""
        if save_as_mode == "CustomName":
            save_as = safe_render(p.get("SaveEmailsAs"))
            if save_as is None:
                return None
            extra = f", save_as={save_as}"
        return [
            f"{prefix}{node.output_var} = outlook_actions.save_outlook_email_messages("
            f"{instance}, {account}, {_as_list_expr(emails)}, {save_to}, "
            f"save_as_mode={save_as_mode!r}{extra}, save_format={save_format!r})"
        ]

    # 知見208: `SendEmailThroughOutlook`の兄弟セレクタ2件(`SendEmailFrom`は`Account`/
    # `OtherMailbox`で固定、`SendEmail`は`SendFrom`が`Hide<>()`されている)。
    _SEND_EMAIL_FROM_BY_ACTION = {
        "Outlook.SendEmailThroughOutlook.SendEmail": "Account",
        "Outlook.SendEmailThroughOutlook.SendEmailFromMailbox": "OtherMailbox",
    }
    send_email_from = _SEND_EMAIL_FROM_BY_ACTION.get(action_id)
    if send_email_from is not None:
        instance = safe_render(p.get("Instance"))
        account = safe_render(p.get("Account"))
        send_to = safe_render(p.get("SendTo"))
        subject = safe_render(p.get("Subject", ""))
        body = safe_render(p.get("Body", ""))
        cc = safe_render(p.get("CC", ""))
        bcc = safe_render(p.get("BCC", ""))
        is_body_html = safe_render(p.get("IsBodyHtml", False))
        is_draft = safe_render(p.get("IsDraft", False))
        if None in (instance, account, send_to, subject, body, cc, bcc, is_body_html, is_draft):
            return None
        extra = ""
        if send_email_from == "OtherMailbox":
            send_from = safe_render(p.get("SendFrom"))
            if send_from is None:
                return None
            extra = f", send_from={send_from}"
        attachments = p.get("Attachments")
        attachments_rendered = safe_render(attachments) if attachments else repr(None)
        if attachments_rendered is None:
            return None
        attachments_expr = _as_list_expr(attachments_rendered) if attachments else "None"
        return [
            f"{prefix}outlook_actions.send_email_through_outlook({instance}, {account}, "
            f"{send_to}, {subject}, {body}, cc={cc}, bcc={bcc}, "
            f"attachments={attachments_expr}, is_body_html={is_body_html}, "
            f"is_draft={is_draft}, send_email_from={send_email_from!r}{extra})"
        ]

    return None


def _enum_mode(value: object, *, default: str) -> str | None:
    from ._support import enum_last

    if value is None:
        return default
    result = enum_last(value)
    return result if result is not None else None
