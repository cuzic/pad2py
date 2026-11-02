# トランスパイラ・コードジェネレータのアーキテクチャ設計のベストプラクティス

## トランスパイラ/コードジェネレータの一般的なアーキテクチャ(パーサー→IR→コードジェネレータ)のベストプラクティスは何か?

### Takeaway
古典的な構成は「字句解析→構文解析(AST構築)→(中間表現への変換)→意味解析/チェック→コード生成」というパイプラインであり、Jinja2のようなテンプレートエンジンの内部実装自体もこの構成(lexer→parser→identifier analyzer→code generator)を踏襲している。各フェーズを独立したパスに分離し、ASTを中心に各処理(最適化・出力・解析)をVisitorパターンで差し替え可能にするのが共通の設計原則。

### Cited Findings
- Jinja2(テンプレートエンジンそのものもコード生成器であり、Pythonのコード生成の大部分を支える)の内部コンパイラは「Lexer > Parser > identifier analyzer > code generator」という4段のパイプラインを持つ — [Code Generation in Python: Dismantling Jinja (PyCon 2012)](https://pycon-archive.python.org/2012/schedule/presentation/246)
- Robert Nystromの"Crafting Interpreters"(jlox実装)では、スキャナがソーステキストをトークン列に変換し、パーサーがトークン列からAST(各ノードが構文単位を表す)を構築し、インタプリタ(ここではコードジェネレータに相当)がそのツリーを走査して実行(または出力生成)する、という3段構成が取られている — [Review of Crafting Interpreters](https://tinycomputers.io/posts/review-of-crafting-interpreters-by-robert-nystrom.html)
- パーサーは構文エラーの検出も兼ねる(パイプラインの早い段階でエラーを洗い出す設計) — [同上]
- AST上の各処理(最適化・プリント・コード生成)を個別のVisitorクラスにパッケージ化し、各ノードクラスにacceptメソッドを持たせる設計が、大学のコンパイラコース教材で標準的に教えられている — [UW CSE401 AST lecture](https://courses.cs.washington.edu/courses/cse401/24au/lectures/H-ASTs.pdf)
- 実務者の例(CodeSmith Generatorのテンプレートパーサー)でも、ASTを構築した後にVisitorを走らせて変換・出力を行う設計に移行し、「新しい変換を追加するには新しいVisitorを書いてパイプラインに差し込むだけで済む、よりクリーンでシンプルで拡張性の高い解決策」になったと報告されている — [CodeSmith Generator 6.0 Progress Report](https://blog.codesmithtools.com/codesmith-generator-6-0-template-parser-progress-report-part-2/)
- MarkdownコンパイラのチュートリアルではASTノード種別ごとに1つのVisitorを用意し、各Visitorが生成コード(例: HTML)を返す設計を取り、別の出力形式(例: XML, ODT)が必要な場合は新しいジェネレータ(Visitor実装)を追加するだけで対応できると説明している — [Writing a Markdown Compiler – Part 3](https://blog.beezwax.net/writing-a-markdown-compiler-part-3/)
- Visitorパターンを使わない場合、セマンティック解析やコード生成などASTを走査する処理ごとに個別のswitch/caseロジックが必要になり、新しいノード型を追加するたびに全ての箇所を修正する必要が生じるという設計上の問題が指摘されている — [ARO-0061 language proposal](https://github.com/arolang/aro/discussions/747)
- Martin Fowlerの"Domain-Specific Languages"は、外部DSL実装の章で構文解析戦略、出力生成戦略(code generation strategies)を扱っており、トランスパイラのフロントエンド/バックエンド設計に直接関連する内容を含む(ただし検索結果は目次レベルの情報のみで、具体的な推奨事項の原文は未確認) — [Domain-Specific Languages (Pearson)](https://www.pearson.com/en-us/subject-catalog/p/domain-specific-languages/P200000008993/9780131392809)

### Inferences
- PAD(XML/JSON形式のフロー定義)→Python変換においても、「パーサー(PAD定義の読み込み・構造化)→IR(アクション・制御フロー・変数のモデル)→コードジェネレータ(Pythonソース出力)」の3層構成を取り、各層を独立してテスト可能にすることが王道と考えられる。
- コード生成部分はVisitorパターン(IRノード種別ごとにディスパッチするメソッド)で実装すると、将来PAD以外のアクション種別や出力言語(例: JavaScript版)を追加する際の拡張性が高まる。

### Gaps
- Dragon Book(Compilers: Principles, Techniques, and Tools)自体からの直接引用は検索で得られず、一般的によく知られる知見(字句解析→構文解析→意味解析→中間表現生成→最適化→コード生成)の記述は本調査では未検証(ツール予算の制約により書籍原文へのアクセスは行っていない)。
- Fowlerの"Domain-Specific Languages"の「出力生成戦略」の具体的な分類(テンプレート方式 vs ツリー構築方式など)は目次情報のみで、本文内容は未取得。

---

## 中間表現(IR)を設計する際に考慮すべき点は何か? 特に「アクションのシーケンス+制御フロー+変数スコープ」を表現するためのASTやIRの設計パターンにはどのようなものがあるか?

### Takeaway
IR設計は「各最適化・各処理パスがローカルな情報だけで判断できるようにする」という原則に基づいて選択されるべきであり、制御フローは明示的なジャンプ/ラベルで表現する基本ブロック(CFG)方式、変数は名前付きオペランド(レジスタベース)またはSSA形式で表現するのが典型的。スコープはIRの構造そのものではなく、シンボルテーブル側の属性(ネスト深度・型・位置・有効範囲)として管理するのが一般的。

### Cited Findings
- IR設計の統一原則は「ローカルな情報だけで判断を下せるようにすること(being able to make decisions with only local information)」である — [What I talk about when I talk about IRs](https://bernsteinbear.com/blog/irs/)
- 制御フローをジャンプとラベルとして明示化することで、線形なアセンブリから基本ブロックのCFGへと変換され、最適化器がホットパスとコールドパスを並べ替えられるようになる(ジャンプの明示化によりブロックが位置独立になるため) — [同上]
- 基本ブロック(basic block)は「1つの入口と1つの出口を持つ直線的な命令列」と定義される — [IITKGP Lect10 compiler slides](https://cse.iitkgp.ac.in/~goutam/IIITKalyani/compiler/lect/Lect10.pdf)
- SSA(Static Single Assignment)形式では各変数が1回だけ定義され、名前がその定義命令を一意に指すため、名前がコンテキストに依存せず解析が単純化される — [What I talk about when I talk about IRs](https://bernsteinbear.com/blog/irs/)
- レジスタベースのIRでは、ローカル変数やスタックという概念が消え、すべてがIR変数になる。解析結果はノードに直接(ポインタ等で)アタッチする方が、別テーブルで管理するより良い設計とされる — [同上]
- スコープはIRの制御構造ではなくシンボルテーブルで管理するのが一般的であり、シンボルテーブルのフィールドとして「レキシカルなネスト深度」が挙げられ、スコープ情報は「いつ変数を非活性化するか」を知るために各変数エントリに付与される — [CSE compiler lecture notes検索結果まとめ](https://www.cse.iitk.ac.in/users/swarnendu/courses/spring2020-cs335/Intermediate%20Representations.pdf) (※検索結果の要約であり原文直接確認はしていない)
- IR設計は「構造的(structural)・ハイブリッド・線形(linear)」の分類があり、抽象度のレベルがどの最適化が可能かを決める。高レベルIRは構造化された制御フローと変数名を保持し型チェックやインライン化に向き、低レベルIRはターゲットマシンに近い — [同上検索結果まとめ]
- Sea of nodes(グラフ型IR)はデータと制御の両方をエッジとして表現し、ノードはスケジューリングされるまで順序を持たない。この形式は抽象解釈に向くとされる一方、「specification reification」(型チェックや高速パスなどオペレーションの完全なセマンティクスをIRに展開すること)はIRの肥大化や最適化の遅延というトレードオフを伴う — [What I talk about when I talk about IRs](https://bernsteinbear.com/blog/irs/)

### Inferences
- PADのフロー(アクションのシーケンス+If/Loop等の制御フロー+変数)を表現するIRとしては、低レベルのCFG/SSAのような最適化志向の設計は過剰であり、むしろ「構造化された制御フロー(If/Loop/Sequenceノードを木構造で保持する高レベルIR)」+「シンボルテーブルによる変数スコープ管理」という高レベルIR寄りの設計が適している可能性が高い。これはBlockly等のブロックベースツールがネストしたブロック構造をそのまま保持する設計(後述)とも整合する。
- 変数スコープについては、PADの変数(グローバルフロー変数、Loop内のローカル変数等)をIRノードの属性ではなく、Pythonコード生成時に解決するシンボルテーブル(名前→型/スコープのマッピング)として別管理するのが定石と考えられる。

### Gaps
- 「アクションのシーケンス+制御フロー+変数スコープ」を表現する専用のAST/IR設計パターン(例: 業務フロー言語やRPAツール向けのIR設計)についての先行研究・業界記事は検索で見つからなかった。一般的なコンパイラのIR理論(CFG, SSA, Sea of Nodes等)からの類推にとどまる。
- シンボルテーブルによるスコープ管理の具体的なベストプラクティス(ネストしたスコープのチェーン探索、shadowingの扱い等)について、コンパイラ理論の教科書レベルを超える一次資料は本調査では未確認。

---

## テンプレートベースのコード生成(Jinja2等)と、AST構築+コードフォーマッタ(libcst, ast.unparse, black)方式、それぞれのメリット・デメリットは?

### Takeaway
テンプレート方式は「読みやすく、構造が複雑な大きいファイルの生成」に向き、AST構築方式は「小さく精密なコード変更」に向くという整理がある。Python標準の`ast`モジュールはセマンティクス保持を目的とした簡潔な構造だが非可逆(コメント・空白・改行スタイルを失う)であり、再出力(unparse)した結果はフォーマッタ(black等)に通す運用が実務的。LibCSTはコメント・空白を完全に保持する可逆なCST(Concrete Syntax Tree)で、既存コードの編集(codemod)には強いが、パースが`ast`より遅く、同じモジュールでも木がより複雑になる。

### Cited Findings
- Jinja2の作者自身が、Jinja2の内部コンパイラは「レキサ→パーサ→識別子解析→コードジェネレータ」というパイプラインを持ち、PythonバイトコードではなくPythonソースコードを出力する設計を選んだと説明している — [Code Generation in Python: Dismantling Jinja](https://pycon-archive.python.org/2012/schedule/presentation/246)
- 同じ講演で、バイトコードは「ドキュメント化されておらず実装依存」であるためデバッグが困難であり、AST経由の生成の方がデバッグしやすいと述べられている。一方でASTノード生成には全ノードに行番号・列番号を明示的に指定する必要があるというコストがある — [同上]
- 一般的な整理として「テンプレートベース: 複雑な構造を持つ大きいファイルに向く」「AST構築: 小さく精密なコード変更に向き、大量のコードを生成すると冗長になる」という対比が示されている(二次資料) — [Code Generation Patterns — Core Concepts](https://smarttldr.pages.dev/en/topic/python-code-generation-patterns/core)
- コード生成(テンプレート実行)は信頼できる入力に対して、ビルド時またはインポート時に行うべきであり、任意のユーザー文字列に対して実行すべきではないという安全性の指摘がある — [同上]
- Python標準`ast`モジュールについて、LibCSTの公式ドキュメントは「セマンティクスの保持には優れており構造が比較的単純」であり、コンパイラや型チェッカーなど意味が重要な場面に向くと評価する一方、「非可逆であり元のソースを再現できない」「コメントが失われる」「ファイル末尾の改行の有無や改行コード(`\n`/`\r`/`\r\n`)の種類も記録されない」「引数間の空白も失われるためフォーマットを保持したコード再生成ができない」と明記している — [Why LibCST?](https://libcst.readthedocs.io/en/latest/why_libcst.html)
- LibCSTは「可逆(lossless)であり、完全に再出力(reprint)できる」ことを特徴とし、コードをAST同様の意味的ノードにパースしつつ、空白の所有権を各ノードに細かく割り当てることで複雑な変更の手間を減らしている。完全に型付けされており、各ノードの子要素が明確に定義されている — [同上]
- LibCSTの欠点として、「空白操作だけに特化したツール(例: Black)は、prefix文字列ではなく空白ノードを操作する必要があるためLibCSTでは構築しにくい」「同じモジュールに対応する木が`ast`より複雑になる(例: 空白を保持するために`Comma`ノードが必要)」「パース速度は`ast`より常に遅い」と明記されている — [同上]
- GitHub上の議論では、「新規にPythonコードを生成する」用途に限れば、LibCSTに標準`ast` + 自動フォーマッタ(Black等)に対する説得力のある優位性はない、という実務者の意見が示されている(一意見であり、ベンチマークではない) — [LibCST Discussion #792](https://github.com/Instagram/LibCST/discussions/792)
- lib2to3のCST(可逆だがASTのような意味的構造を持たない)は、関数へのパラメータ追加・削除の際に`COMMA`ノードの保持が必要など複雑な操作が難しく、「意味を変更しないツール(Blackなど)」に向いているとLibCSTドキュメントは位置づけている — [Why LibCST?](https://libcst.readthedocs.io/en/latest/why_libcst.html)

### Inferences
- 「既存の」PADのアクション定義を読み込むだけで新規にPythonソースを生成する(既存Pythonコードの編集ではない)という本プロジェクトの性質上、LibCSTの強み(フォーマット保持・既存コード編集)は直接の必要性が薄く、`ast`モジュールでASTを構築し`ast.unparse`で文字列化、その後`black`等のフォーマッタで整形するという構成、あるいはJinja2のようなテンプレートベースの出力生成の方が実装コストに対して合理的である可能性が高い。
- 生成コードが「アクション→対応するPython関数呼び出し1行(+エラーハンドリングのラップ)」のような比較的規則的なパターンが多い場合は、テンプレート方式(各アクション種別に対応するJinja2テンプレート)が読みやすさ・保守性の面で有利と考えられる。逆に、変数名の衝突回避やインデント管理、スコープに応じた変数宣言挿入など構造的な正しさが重要な場合はAST構築方式が安全。
- 両方式のハイブリッド(アクション単位の小さなコード断片はテンプレートで生成し、それらをASTレベルで組み立ててインデント・スコープを機械的に正しく保つ)という設計も現実的な選択肢になりうる。

### Gaps
- `ast.unparse`自体の既知の制限(コメント非対応、特定の構文での出力の非最適性など)について、公式ドキュメントからの直接引用は本調査では未取得(検索結果はLibCSTとの比較的意見にとどまり、`ast.unparse`固有の議論は見つからなかった)。
- astor(サードパーティのASTから Pythonソースへのコード生成ライブラリ)についての具体的な評価・比較情報は検索結果からほとんど得られなかった(StackShareのスター数程度の情報のみ)。

---

## ビジュアルプログラミング/ローコードツールからコードを生成する既存の実例(Blockly, Node-RED, Scratch-VM)はどのような設計を取っているか? そこから得られる教訓は?

### Takeaway
Blocklyは「言語ごとのコードジェネレータ(言語レベルの整形・インデント・コメント規則を担当)」と「ブロックごとのコードジェネレータ(各ブロック型×各言語で1関数、文字列を返す)」という2層構造を取り、ブロックの木構造をそのまま再帰的に文字列へ変換する設計になっている。Node-REDはビジュアルフロー(JSON配列)を「コードを生成する」のではなく「JSONからノードオブジェクトを直接インスタンス化して実行する」設計であり、コード生成ではなくインタプリタ型の実行モデルを取っている。Scratchは上位レイヤー(Scratch Blocks, Blocklyのフォーク)ではコード生成を行わず、専用のVM(インタプリタ)がブロックを実行する設計を取り、パフォーマンスが必要な場合はTurboWarpのような派生プロジェクトがJITコンパイラを追加している。

### Cited Findings
- Blocklyのコード生成は「`Blockly.Generator`という共通基底クラス」を持ち、JavaScript/Python/PHP/Dart/Luaなど各ターゲット言語ごとにサブクラスを実装してルールを与える設計である — [pxt-blockly generator architecture (DeepWiki)](https://deepwiki.com/microsoft/pxt-blockly/4.1-generator-architecture)
- 同ジェネレータは演算子の優先順位(括弧の付加)、予約語の衝突回避、ブロックごとの関数、初期化/終了処理のライフサイクルステップを扱う(DeepWikiによる二次的要約) — [同上]
- Blockly公式ドキュメントでは、コード生成を「言語コードジェネレータ(language code generators)」と「ブロックコードジェネレータ(block-code generators)」の2層に明確に分離している。言語コードジェネレータはコメントの整形・ステートメントのインデント・文字列のクォートなど言語固有の規則を扱い、公式にはJavaScript ES5, Python 3, Lua 5.1, Dart 2, PHP 7の5つが用意されている — [Blockly: Generating Code](https://docs.blockly.com/guides/create-custom-blocks/generating-code)
- ブロックコードジェネレータは「各ブロック型・各言語ごとに1つの関数を書く」設計であり、各関数はそのブロックのコードを文字列として返し、言語ジェネレータがそれらを呼び出す。比較演算ブロックは`'a < b'`のような式形式の文字列を返し、if文ブロックは波括弧と改行を含む文形式の文字列を返す、という具体例が示されている — [同上]
- Blockly公式ドキュメントは明示的に「ブロックを直接実行することはできない。コード文字列を生成し、それを実行する」という設計方針を述べており、コード生成とコード実行(アプリケーション固有)を明確に分離している — [同上]
- Node-RED: エディタはキャンバスの内容をJSON配列としてランタイムに送信し、デプロイ時にランタイムがそのJSONからノードオブジェクトを直接インスタンス化する。フルデプロイでは現在のノード群を停止・破棄し、JSONフロー定義内の各ノードをループして対応する型のノードオブジェクトを新規作成し、その設定を渡す、という設計 — [How does Node-RED deploy work?](https://groups.google.com/g/node-red/c/cl3mFPVYhDg)
- Node-REDのコードは`red/runtime/nodes/flows/Flow.js`のFlowオブジェクトが、含まれる全ノードの生成・開始・停止を担当する構造になっている — [同上]
- Node-REDはメッセージキューサービスではなく、コアランタイムによって束ねられた多数の相互接続モジュールから構成されるNode.jsアプリである、という説明がフォーラムで共有されている — [Internal architecture of Node-RED (Discourse)](https://discourse.nodered.org/t/internal-architecture-of-node-red/76733)
- 実行順序は固定スケジュールではなく呼び出しの連鎖(メッセージパッシング)に従う。非同期の変更競合を避けるためメッセージがクローンされることがある — [同上フォーラムスレッド要約]
- Node-REDと同じJSONフロー定義を、Node.js以外のランタイムで実行する試みも存在する(例: Rust実装のEdgeLink、MCU向けのnode-red-mcu)。これはNode-REDのフロー形式が「実行エンジン非依存の中間表現」として扱われていることを示す — [EdgeLink](https://github.com/oldrev/edgelink), [Node-RED as a formal workflow description (Discourse)](https://discourse.nodered.org/t/node-red-as-a-formal-workflow-description/76539/2)
- Scratch Blocks(Google Blocklyのフォーク)は、Blockly本来のコードジェネレータ機能を意図的に使わず、代わりにScratch VM(専用の実行エンジン)にブロックの実行を委ねる設計を取っている — [Scratch Blocks README要約](https://github.com/LLK/scratch-blocks)
- TurboWarp(Scratch VMのサードパーティフォーク)は、ブロックをJITコンパイルするコンパイラを追加しており、その詳細は`src/compiler`ディレクトリにある — [TurboWarp scratch-vm](https://github.com/TurboWarp/scratch-vm/)

### Inferences
- Blocklyの「言語ジェネレータ×ブロックジェネレータ」の2層分離は、PAD→Python変換における「Python言語レベルの整形規則(インデント、import文の集約、コメント形式)」と「PADアクション種別ごとの変換ロジック(例: `Open Browser`アクション→`webdriver.Chrome()`呼び出し)」を分離する設計に直接応用できる。各PADアクション型に対して1つの「コードジェネレータ関数」を実装し、共通の言語レベルのユーティリティ(インデント管理、変数命名規則の適用)を別クラスに切り出す構成が妥当と考えられる。
- Node-RED/Scratch VMの実例は「ビジュアル定義から都度コードを生成する」のではなく「ビジュアル定義を直接解釈実行する(インタプリタ型)」という代替アーキテクチャも存在することを示している。PAD→Python変換ツールの目的が「人間が読める・保守できるPythonソースを出力すること」であれば、Blockly型(コード生成)の方が目的に合致するが、仕様上「正確な実行」が最優先であればNode-RED型(インタプリタ)も検討の余地がある、という設計判断の軸が得られる。
- Scratch/TurboWarpの教訓は、「まずシンプルな実行エンジン(あるいは素直なコード生成)で正しさを確保し、パフォーマンスが問題になった場合に専用の最適化層(JIT等)を後付けする」という段階的アーキテクチャの有効性を示唆する。PAD→Python変換でも、まず素直な1アクション=1行程度の変換を確立し、その後に最適化(ループの単純化、冗長な変数の除去等)を別パスとして追加するのが安全である。

### Gaps
- 上記のBlockly公式ドキュメントのページは、優先順位(parentheses)の扱いやvalueブロック/statementブロックの正式な区別について、別ページへのリンクのみを示し本文内容は含まれていなかったため、この部分の具体的な設計は未確認。
- Scratch本家(LLK/scratch-vm)自身のブロック実行・内部表現の設計資料は検索で直接見つからず、上位のScratch Blocksの説明とTurboWarp(フォーク)の情報から推測するに留まった。本家VMの一次資料(ソースコードやブログ)の追加調査が必要。

---

## 「忠実な1:1変換」と「意味を保った上での最適化・簡略化」のトレードオフをどう扱うべきか?

### Takeaway
実務的な議論では「まず振る舞いを保った忠実な変換(parity)を行い、イディオム的な書き換え・最適化は別フェーズで行う」という段階的アプローチへの支持が多いが、忠実な変換をそのまま「成果物」とすることには強い批判もある(ターゲット言語の実行モデルに合わないオーバーヘッドを引き継ぐ、慣用的でないコードが保守性を損なう等)。また、1:1変換が「機能的に同一」であっても「運用上は間違っている」可能性があるという指摘があり、検証(特性テスト・出力diff・段階的カットオーバー)がコストの実質的な分岐点になるとされる。

### Cited Findings
- 「パリティ(振る舞いの同一性)を非自明なリライトの第一段階とし、イディオム的なリファクタリングは後のフェーズで行うべき」という意見がHacker News上の議論で共有されている — [HN discussion](https://hn.nuxt.dev/item/47120899)
- 成熟したプロダクト(例: Ladybirdブラウザ関連の議論)では、ユーザー向けの振る舞いを壊してはならないため「まず純粋な変換ステップ、その後にリファクタリング」という同じ主張がなされている — [同上]
- Python→Rustトランスパイラを批判する記事は、「忠実な変換の結果はRustの構文に包まれたPythonのオーバーヘッドをそのまま引き継ぐだけ」であり、ホットパス(通常コード全体の10%未満)は手動で書き直すべきだと主張している — [The Bit-Exact Python to Rust Transpiler Trap](https://dev.to/xu_xu_b2179aa8fc958d531d1/the-bit-exact-python-to-rust-transpiler-trap-why-faithful-translation-is-the-wrong-goal-1nck)
- COBOL→Javaの逐語的トランスコーダに対するベンダー批判記事は、「出力は合法なJavaだが慣用的なJavaでもCOBOLでもなく、移行のそもそもの目的である保守性向上・採用のしやすさという利点を損なう」と論じている — [A COBOL Migration you do NOT want](https://www.semanticdesigns.com/Products/Services/EraneaNACA.html)
- 移行ツールのベンダー自身も「変換ツールの出力は粗雑であり、人間によるレビューを前提とする」と位置づけており、変換後のクリーンアップ作業に変換作業自体の約2倍の時間を見込むべきだという意見もある — [Translation Myth Busters](https://greatmigrations.atlassian.net/wiki/x/6A4Y) (※後半の「2倍」の見積りは別記事由来、出典は検索結果の要約に基づく)
- 2026年のエッセイは「行単位の忠実な翻訳は機能的に同一であっても運用上は誤りうる」と論じ、理由として未文書化の振る舞いやデータ品質の問題がコード自体には現れないことを挙げ、変換前の特性テスト(characterization tests)・変換中の出力diff・段階的カットオーバーとロールバックを推奨している — [The rewrite is cheap, now being right isn't](https://tianpan.co/blog/2026-07-02-the-rewrite-is-cheap-now-being-right-isnt)

### Inferences
- PAD→Python変換においても、まずPADの各アクションをできるだけ忠実に(1アクション=1つの明確なPython呼び出しまたは数行のブロックとして)変換する「忠実な変換モード」をデフォルトとし、ループの単純化や冗長な変数の除去といった最適化は、忠実な変換結果を入力とする別パス(オプトイン可能な最適化ステップ)として分離するのが、上記の議論から導かれる穏当な設計と考えられる。これにより「生成コードがPAD側の元の処理と対応していることが追跡できる」という検証可能性(traceability)と、「読みやすいPythonコードを作る」という目的を両立しやすくなる。
- 「忠実な変換=成果物として十分」という考え方には複数の実務者から明確な反論があるため、少なくとも生成コードに対する人間のレビュー工程、またはPAD側の元の処理内容を追跡できるコメント(どのPADアクションから生成されたか)を残す設計が望ましい。

### Gaps
- このトレードオフに関する学術的・コンパイラ理論的な正式な議論(例えば「semantics-preserving transformation」の形式的な枠組みに関する論文)は本調査の検索範囲では見つからず、実務者のブログ・フォーラムの意見に基づく整理に留まる。
- 「忠実性」と「最適化」を両立させる具体的な設計パターン(例: 二段階IR、注釈付きIRでトレーサビリティを保持する手法など)についての直接の文献は見つからなかった。

---

## エラーハンドリング・未対応アクションへの対処(変換不能な部分の扱い、警告コメントの挿入、フォールバック戦略)についてのベストプラクティスは?

### Takeaway
複数のツール・プロジェクトで共通して見られるパターンは「失敗箇所に目立つマーカーを残す」という方針であり、具体的には(a) 未対応構文をコメントとして元のまま出力し`TODO`マーカーを付ける、(b) 明示的なフォールバック機構(フォールバック要素/子要素が定義されていればそれを使い、無ければ実行時エラーとする)、(c) 警告を黒塗りにせず構造化された診断情報として収集する、(d) 「サイレントに握りつぶす」よりも「ビルドを失敗させる」方を優先する、という4つのアプローチが挙げられる。単一の権威的な標準スタイルガイドは見つからなかった。

### Cited Findings
- コード変換ツール(Rosetta)のGitHub Issueでは、変換不能な構文に遭遇した場合、元のソースをコメントとして出力し`//TODO`マーカーを付けるべきだと提案されている。「完全に変換されたファイルにはならないかもしれないが、少なくとも作業可能な骨格(skeleton)が残る」という理由付けがされている — [andry-tino/Rosetta#24](https://www.github.com/andry-tino/Rosetta/issues/24)
- XSLTC(XalanのXSLTコンパイラ)は未対応要素への対処として正式な「フォールバック」機構を持つ。フォールバック子要素は、親要素が未対応の場合にのみ有効化・変換される。フォールバック子要素が存在しない場合、その要素がインスタンス化される際に実行時エラーが発生する設計になっている — [Xalan XSLTC Fallback.html](https://xalan.apache.org/xalan-j/apidocs/src-html/org/apache/xalan/xsltc/compiler/Fallback.html), [UnsupportedElement.html](https://xalan.apache.org/xalan-j/apidocs/src-html/org/apache/xalan/xsltc/compiler/UnsupportedElement.html)
- Rustコンパイラのあるコミットでは、「未対応の構文に遭遇した場合は出力から静かに取り除くのではなく、コンパイルを失敗させる」という方針転換が行われ、`TODO`プレースホルダーが、未対応の構文名を明示した`Not_implemented`例外に置き換えられた — [Rust commit mirror](https://cdn05042023.gitlink.org.cn/dnrops/rust/commit/9d0d350d2cb62a0396c2d186fcfb936edfc150e8)
- あるトランスパイラのPR(stompgg/chomp)では、未対応構文に関する警告を収集する専用の診断モジュールを追加し、コード生成前にASTをスキャンして構文種別ごとにグループ化したサマリーを出力する設計が取られている — [stompgg/chomp#57](https://gh.r-mj.com/stompgg/chomp/pull/57)
- あるプロジェクト(eQuantic)のドキュメントでは、未対応構文は「警告ではなくエラーとして扱い、元のコードをそのまま通過させてはならない」という方針に修正された、という経緯が記録されている — [eQuantic UI wiki history](https://github.com/eQuantic/equantic-ui/wiki/SupportedFeatures-pt-BR/_history)

### Inferences
- PAD→Python変換ツールにおいては、未対応のPADアクションに遭遇した場合、(1)デフォルトでは生成コード中に「元のPADアクション定義をコメントとして埋め込み、`# TODO: unsupported action <ActionType>`のような明示的マーカーを付与する」フォールバック戦略を採用し、(2)変換全体のサマリーとして「何件のアクションが変換できたか/未対応だったか」を構造化された診断レポートとして出力する、という二段構えの設計が、調査した複数のプロジェクトの実践と整合する。
- 「サイレントに握りつぶす」ことは複数のプロジェクトで明確に否定されているため、未対応アクションがあっても変換処理自体は(デフォルトでは)完走させつつ、目立つ警告・TODOコメントを残すことで、ユーザーが変換結果をレビューする際に見落とさないようにする設計が妥当と考えられる。ただし「厳格モード」として未対応アクションがあればエラーで停止する選択肢も、CI/CD等での利用を想定するなら用意する価値がある。

### Gaps
- RPA/ローコードツール特有の「アクション単位でのフォールバック戦略」についての業界記事・ベストプラクティス集は見つからず、汎用的なコンパイラ/トランスパイラの事例からの類推にとどまる。
- 「警告コメントの挿入」の具体的なフォーマット標準(どこに・どういう情報を含めるべきか)についての統一的な指針は見つからなかった。

---

## テスト戦略(生成されたコードの正当性を保証するためのゴールデンテスト、スナップショットテスト等)についての知見は?

### Takeaway
コード生成ツールの検証では「固定入力に対して生成器を実行し、その出力をレビュー済みのベースライン(ゴールデン/スナップショット)として保存し、以降の実行結果をそれと比較する」というパターンが広く使われている。多くの実装は単純なテキスト比較に加えて「生成されたコードをターゲット言語の実際のコンパイラ/インタプリタに通す」という二段目の検証層を重ねており、これによりテキスト一致だけでは検出できない型エラー等を捉えている。

### Cited Findings
- OpenAPI用の多言語コード生成ツール(openapi-nexus)は、生成した各ファイルをバイト単位で`.golden`ファイルと比較するゴールデンテストを採用している。さらに、ターゲット言語の実際のコンパイラをゴールデン出力に対して実行する第二の検証層を持ち、これによりスナップショット比較だけでは検出できない型エラーを捕捉している。ゴールデンファイルは`UPDATE_GOLDEN=1`環境変数で再生成し、生成器が新しいファイルを追加したのに対応するゴールデンファイルが無い場合はテストが明確なメッセージで失敗する設計になっている — [openapi-nexus golden_testing.md](https://docs.rs/crate/openapi-nexus/latest/source/docs/src/golden_testing.md)
- フルスタックのコンパイラ駆動フレームワークWaspは、生成コードの主要な検証手段としてスナップショットテストを用いており、著者らは「スナップショットテストは少ないテストコードで高い確信度を与える」と述べている。ゴールデンスナップショットはGitで管理されているため、各プルリクエストで生成コードの変更差分がそのまま可視化される — [Wasp snapshot testing (検索結果要約)](https://github.com/unsplash/intlc/issues/35)(※元記事URLは検索結果に直接含まれず、intlc issueでの言及経由)
- Rocコンパイラは、コンパイラの各ステージごとにゴールデンのベースライン出力を生成する専用のスナップショットツールを持ち、現在の出力がベースラインと異なる場合にテストを失敗させる — [Roc snapshot_tool](https://git.joshthomas.dev/language-servers/roc/src/commit/adfa93d77e988ce0ef5f3abce48dc98e86e7d098/src/snapshot_tool)
- FHIR→Rustのコード生成ツール(rh-codegen)は、代表的な入力定義からRustコードを生成し、それを保存済みの期待出力と比較するゴールデンファイルテストを持つ — [rh-codegen golden_tests.rs](https://docs.rs/crate/rh-codegen/0.2.0/source/tests/golden_tests.rs)
- C#のSource Generatorsに関する2026年4月のガイドは、「決定的で安定した出力に対しては明示的な期待値アサーションを使い、出力が大きい場合や生成器が頻繁に変わる場合はVerifyライブラリ等によるスナップショットテストを使う」という使い分けを推奨している — [Testing C# Source Generators: A Practical Guide](https://www.devleader.ca/2026/04/08/testing-c-source-generators-a-practical-guide)

### Inferences
- PAD→Python変換ツールのテスト戦略としては、(1)代表的なPADフロー定義(XML/JSON)の固定セットを用意し、生成されたPythonコードをゴールデンファイルとして保存・Git管理する、(2)ゴールデンファイルの更新は環境変数等で明示的にトリガーし、差分をレビューしてから承認する、(3)テキスト比較だけでなく、生成されたPythonコードを実際に`python -c`やASTパース、あるいは`py_compile`で構文チェック・実行することで「構文的に正しいPythonである」ことまで検証する、という二層構成が妥当と考えられる。
- 生成されるコードの量や、アクション追加の頻度が高いことを踏まえると、「安定していて変化の少ないコア部分(制御フロー変換など)は明示的なアサーション」「個々のアクションタイプの変換結果は広くスナップショットテストでカバーする」という使い分け(C#記事の推奨)がPADアクションの多様性(数百種類のアクション)に対して実用的である可能性が高い。

### Gaps
- RPA/ローコードツールのコード生成に特化したテスト戦略(例: 生成されたPythonコードを実際に実行して元のPADフローと同じ結果が得られることを検証するE2Eテストの設計)についての具体的な事例は見つからなかった。
- ゴールデンテストにおける「意図的な差分」と「意図しない regression」を区別するためのレビュープロセスの具体的な運用例(例: 差分の自動要約、diffの可読性向上の工夫)についての詳細情報は本調査では未取得。
