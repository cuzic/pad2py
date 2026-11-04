"""PAD Tier 1/Tier 2/Tier 3アクションの変換ロジック(FCIS的な純粋関数コア)。

`pad_codegen`のaction_idディスパッチ(`pad_codegen/actions/`)とは独立したレイヤー。
Tier 1(Text/DateTime/Variables/File/Folder/Compression/Cryptography)・Tier 2
(Database/Web/XML/Cmd/Clipboard)・Tier 3(Excel/Word/PowerPoint/PDF)各モジュールの
`[Throws]`タグや既定値・非自明な挙動を関数単位で再現し、個別にユニットテストする。

Tier 3(Excel/Word/PowerPoint)は実機のPADが**ライブのOffice COMインスタンス**を
操作するのに対し、この層は`openpyxl`/`python-docx`/`python-pptx`でファイルを
直接編集する——マクロ実行・フィルタ/ソート・自動調整・COMアタッチ等、ライブアプリ
でしか意味を持たない機能は意図的にスコープ外とし、`NotImplementedError`で明示する
(詳細は各モジュールのdocstringを参照)。PDFはPAD自体がPDFium(ライブアプリ不要の
自己完結ライブラリ)ベースなのでこの制約は無い。

action_idからこの層の関数を呼び出す結線(codegenへの統合)は、実機でDSL構文・
action_id文字列・パラメータ直列化形式を確認した後に別途行う——このパッケージ自体は
decompileベースの推定実装であり、exports一覧やaction_id対応表はまだ持たない。
"""
from __future__ import annotations

from .errors import PadActionError

__all__ = ["PadActionError"]
