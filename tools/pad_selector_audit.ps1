<#
.SYNOPSIS
  PAD(Power Automate Desktop)の `*.Actions.dll` をリフレクションで列挙し、
  `ActionSelectorBase` 派生の兄弟セレクタ一覧を `tools/pad_selector_audit.py`
  の `--dump` が期待する `<TargetClass> | <SelectorClassName> | ActionName=<Name>`
  形式で出力する。

  design/dsl_format_findings.md 知見139以降で確立した「`ActionSelectorBase`
  派生型をリフレクションで列挙し、`ActionName`プロパティを読み取る」監査手法を、
  これまで`clipwire`のアドホックターゲットとして都度書き直していたのを、
  再利用可能なスクリプト資産として1本化したもの
  (design/common_rpa_framework_roadmap.md 層3の残課題)。

.DESCRIPTION
  各DLLについて:
    1. `[System.Reflection.Assembly]::LoadFrom()` でロードする
       (`ReflectionTypeLoadException`は読み込めた型だけを使って継続する)。
    2. 全型をBaseTypeチェーンで遡り、`ActionSelectorBase`(またはその派生、
       例: 名前が`ActionSelector`で始まる型)に行き着く型だけを対象にする。
    3. 対象型の直接の親(`ActionSelector<TTarget>`)から型引数`TTarget`の
       クラス名を取り、対象型自身の`ActionName`プロパティ(インスタンス化して
       `GetValue()`)を読み取る。
    4. `<TTarget> | <対象型名> | ActionName=<ActionName>` の形式で1行出力する。

  読み取り専用(`Execute()`は一切呼ばない、インスタンス化のみ)——PAD Designerの
  UIには一切触れないため、他セッションがVM上のDesignerを操作中かどうかに関わらず
  安全に実行できる(design/dsl_format_findings.md 知見の「busy/idle問わず安全な
  VM操作」カテゴリ)。

.PARAMETER Dlls
  列挙対象のDLLファイル名の配列(`$Root`からの相対、例:
  "Microsoft.Flow.RPA.Desktop.Modules.Database.Actions.dll")。

.PARAMETER Root
  DLLの置かれているディレクトリ。既定はPAD本体のインストール先。

.EXAMPLE
  .\pad_selector_audit.ps1 -Dlls "Microsoft.Flow.RPA.Desktop.Modules.Excel.Actions.dll"
  # => tools/selector_dumps/Excel.txt相当の内容を標準出力へ書き出す
#>
param(
    [Parameter(Mandatory = $true)]
    [string[]]$Dlls,

    [string]$Root = "C:\Program Files (x86)\Power Automate Desktop"
)

foreach ($dllName in $Dlls) {
    $path = Join-Path $Root $dllName
    if (-not (Test-Path $path)) {
        Write-Output "=== $dllName === (file not found)"
        continue
    }

    try {
        $asm = [System.Reflection.Assembly]::LoadFrom($path)
    } catch {
        Write-Output "=== $dllName === LoadFrom failed: $($_.Exception.Message)"
        continue
    }

    $types = @()
    try {
        $types = $asm.GetTypes()
    } catch [System.Reflection.ReflectionTypeLoadException] {
        $types = $_.Exception.Types | Where-Object { $_ -ne $null }
    }

    foreach ($t in $types) {
        # BaseTypeチェーンを遡り、`ActionSelectorBase`(または名前が`ActionSelector`で
        # 始まる基底型)へ行き着くかどうかを確認する——知見139以降の標準判定方式。
        $bt = $t.BaseType
        $isSelector = $false
        $directBase = $t.BaseType
        while ($bt -ne $null) {
            if ($bt.Name -like "ActionSelector*") {
                $isSelector = $true
                break
            }
            $bt = $bt.BaseType
        }
        if (-not $isSelector) { continue }

        $targetName = "(unknown target)"
        if ($directBase -ne $null -and $directBase.IsGenericType) {
            $targetName = $directBase.GetGenericArguments()[0].Name
        }

        try {
            $instance = [System.Activator]::CreateInstance($t)
            $actionNameProp = $t.GetProperty("ActionName")
            if ($actionNameProp) {
                $actionName = $actionNameProp.GetValue($instance)
                Write-Output "$targetName | $($t.Name) | ActionName=$actionName"
            } else {
                Write-Output "$targetName | $($t.Name) | (no ActionName property)"
            }
        } catch {
            Write-Output "$targetName | $($t.Name) | instantiate/read failed: $($_.Exception.Message)"
        }
    }
}
