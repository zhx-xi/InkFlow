; frontend/packages/electron/build/installer.nsh
; F33 CLI 独立发布产物（Issue #168，spec f33-cli-dist §4）
; electron-builder nsis.include 默认解析位置（buildResourcesDir）
;
; 钩子宏机制（electron-builder 26.x NSIS 模板实测，spec §4.1）：
; - customPageAfterChangeDir：目录选择页之后、INSTFILES 页之前（assistedInstaller.nsh
;   模板注释 "you can show custom page here"）——PATH 勾选页
; - customInstall：安装 Section 末尾（installSection.nsh，文件解压后、快捷方式后）——PATH 写入
; - customUnInstall：卸载 Section 开头（uninstaller.nsh，文件删除前，$INSTDIR 仍有效）——PATH 清理
; - 静默安装 /S：页面全部跳过 → 勾选页不执行 → $addCliToPath 保持默认 0 → 不加 PATH
;
; 依赖说明：本文件经 electron-builder 的 sharedHeader include 进生成脚本头部，先于模板
; （MUI2.nsh / multiUser.nsh）被解析——LogicLib / nsDialogs 必须在此自行 include。
; 本文件在安装器与卸载器两次编译中均被 include：安装侧 Page/Var 必须用
; !ifndef BUILD_UNINSTALLER 守卫；卸载侧函数使用 un. 前缀并在 !ifdef BUILD_UNINSTALLER 内定义。

!include "LogicLib.nsh"
!include "nsDialogs.nsh"

; ⚠️ $installMode 是 multiUser.nsh（模板后部）声明的变量——本文件在 sharedHeader 位置被
;    include（先于模板），函数体直接引用 $installMode 会触发 NSIS warning 6000
;    （unknown variable, ignoring）→ 恒走 else 分支（per-machine 安装写错注册表根）。
;    修复：宏体（在模板内展开，$installMode 已声明）把值复制到自有变量 _f33InstallMode，
;    函数体只读 _f33InstallMode（NSIS 3.0.4.1 实测，2026-08-08）。
Var _f33InstallMode

!ifndef BUILD_UNINSTALLER
  Var addCliToPath
  Var addCliToPathCheckbox

  ; 勾选页：目录选择之后、安装开始之前（assistedInstaller.nsh customPageAfterChangeDir 钩子）
  !macro customPageAfterChangeDir
    Page custom AddCliToPathPage AddCliToPathPageLeave
    Function AddCliToPathPage
      nsDialogs::Create 1018
      Pop $0
      ${If} $0 == error
        Abort
      ${EndIf}
      ${NSD_CreateLabel} 0 0 100% 24u "添加 InkFlow CLI 到 PATH（默认不勾）"
      Pop $0
      ${NSD_CreateLabel} 0 24u 100% 32u "将 $INSTDIR\resources\kernel 加入 PATH，可在任意终端使用 inkflow 命令。"
      Pop $0
      ${NSD_CreateCheckBox} 0 64u 100% 12u "添加 InkFlow CLI 到 PATH"
      Pop $addCliToPathCheckbox
      nsDialogs::Show
    FunctionEnd
    Function AddCliToPathPageLeave
      ${NSD_GetState} $addCliToPathCheckbox $addCliToPath
    FunctionEnd
  !macroend
!endif

; 安装末尾：仅勾选时写入 PATH（spec §4.3，幂等去重）
!macro customInstall
  StrCpy $_f33InstallMode "$installMode"
  ${If} $addCliToPath == "1"
    ; kernel（既有行为）→ 追加 mcp 子目录（spec §5.4，同幂等去重逻辑二次调用）
    StrCpy $1 "$INSTDIR\resources\kernel"
    Call AddKernelDirToPath
    StrCpy $1 "$INSTDIR\resources\kernel\mcp"
    Call AddKernelDirToPath
  ${EndIf}
!macroend

; 卸载开头：按精确条目清理 PATH（spec §4.4，幂等；不依赖安装时是否勾选）
!macro customUnInstall
  StrCpy $_f33InstallMode "$installMode"
  ; 按精确条目清理两目录（spec §5.4；幂等，不依赖安装时是否勾选）
  StrCpy $1 "$INSTDIR\resources\kernel"
  Call un.RemoveKernelDirFromPath
  StrCpy $1 "$INSTDIR\resources\kernel\mcp"
  Call un.RemoveKernelDirFromPath
!macroend

!ifndef BUILD_UNINSTALLER
  ; === 安装侧：PATH 写入（spec §4.3）===
  Function AddKernelDirToPath
    ; 目标条目由调用方写入 $1（spec §4.3 内核目录 + §5.4 mcp 子目录二次调用）

    ; SHELL_CONTEXT 跟随安装模式（spec §4.3 / §12 D11）：
    ; per-user（默认）→ HKCU\Environment；per-machine（"all"）→ HKLM\...\Environment
    ${If} $_f33InstallMode == "all"
      SetRegView 64
      ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
    ${Else}
      ReadRegStr $0 HKCU "Environment" "Path"
    ${EndIf}

    ; Path 不存在 → 直接写入目标条目（REG_EXPAND_SZ 语义）
    ${If} $0 == ""
      ${If} $_f33InstallMode == "all"
        WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" $1
      ${Else}
        WriteRegExpandStr HKCU "Environment" "Path" $1
      ${EndIf}
      Call BroadcastEnvChange
      Return
    ${EndIf}

    ; 1000 字符保护：跳过写入并警告，绝不截断写回（spec §7 N4）
    StrLen $2 $0
    ${If} $2 >= 1000
      DetailPrint "跳过写入 PATH：当前 PATH 长度 $2 字符（>= 1000 保护阈值），未添加：$1"
      Return
    ${EndIf}

    ; 去重：按 ';' 分隔段，大小写不敏感（StrCmp 默认）+ 尾部反斜杠归一化（spec §4.3）
    StrCpy $3 $0            ; 待扫描剩余串
    ${Do}
      ; 取出下一段到 $4，并把 $3 推进到该段之后
      StrCpy $4 ""
      StrCpy $5 0
      StrLen $6 $3
      ${Do}
        ${If} $5 >= $6
          StrCpy $4 $3
          StrCpy $3 ""
          ${ExitDo}
        ${EndIf}
        StrCpy $7 $3 1 $5
        ${If} $7 == ";"
          StrCpy $4 $3 $5
          IntOp $5 $5 + 1
          StrCpy $3 $3 "" $5
          ${ExitDo}
        ${EndIf}
        IntOp $5 $5 + 1
      ${Loop}

      ${If} $4 != ""
        Call NormalizeTrailingSlash
        StrCmp $4 $1 0 not_found_segment
          Return          ; 已含目标条目 → 幂等跳过
        not_found_segment:
      ${EndIf}

      ${If} $3 == ""
        ${ExitDo}
      ${EndIf}
    ${Loop}

    ; 未含 → 追加（保持既有 Path 展开语义，REG_EXPAND_SZ）
    StrCpy $0 "$0;$1"
    ${If} $_f33InstallMode == "all"
      WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" $0
    ${Else}
      WriteRegExpandStr HKCU "Environment" "Path" $0
    ${EndIf}
    Call BroadcastEnvChange
  FunctionEnd

  ; 尾部反斜杠归一化：$4 原地去尾 \（驱动根如 "C:\" 保留，防误伤）
  Function NormalizeTrailingSlash
    Push $5
    Push $6
    ${Do}
      StrLen $5 $4
      ${If} $5 <= 3
        ${ExitDo}
      ${EndIf}
      StrCpy $6 $4 1 -1
      ${If} $6 != "\"
        ${ExitDo}
      ${EndIf}
      StrCpy $4 $4 -1
    ${Loop}
    Pop $6
    Pop $5
  FunctionEnd

  ; WM_SETTINGCHANGE 广播：新开终端立即生效（spec §4.3 step 8）
  Function BroadcastEnvChange
    Push $0
    System::Call 'user32::SendMessageTimeout(i 0xFFFF, i 0x001A, i 0, w "Environment", i 0x0002, i 5000, *i r0)'
    Pop $0
  FunctionEnd
!endif

!ifdef BUILD_UNINSTALLER
  ; === 卸载侧：PATH 清理（spec §4.4）===
  Function un.RemoveKernelDirFromPath
    ; 目标条目由调用方写入 $1（与安装写入完全同构；不依赖安装时是否勾选，幂等清理）

    ${If} $_f33InstallMode == "all"
      SetRegView 64
      ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
    ${Else}
      ReadRegStr $0 HKCU "Environment" "Path"
    ${EndIf}

    ${If} $0 == ""
      Return                  ; PATH 无内容 → 无需清理
    ${EndIf}

    ; 1000 字符保护：跳过清理并警告，绝不截断写回（spec §7 N4）
    StrLen $2 $0
    ${If} $2 >= 1000
      DetailPrint "跳过清理 PATH：当前 PATH 长度 $2 字符（>= 1000 保护阈值），条目未移除：$1"
      Return
    ${EndIf}

    ; 按 ';' 分隔，精确匹配删除目标条目（大小写不敏感 + 尾部反斜杠归一化），重建剩余 PATH
    StrCpy $3 $0               ; 待扫描剩余串
    StrCpy $6 ""               ; 重建后的 PATH
    StrCpy $7 "0"              ; 是否删除了目标条目
    ${Do}
      StrCpy $4 ""
      StrCpy $5 0
      StrLen $8 $3
      ${Do}
        ${If} $5 >= $8
          StrCpy $4 $3
          StrCpy $3 ""
          ${ExitDo}
        ${EndIf}
        StrCpy $9 $3 1 $5
        ${If} $9 == ";"
          StrCpy $4 $3 $5
          IntOp $5 $5 + 1
          StrCpy $3 $3 "" $5
          ${ExitDo}
        ${EndIf}
        IntOp $5 $5 + 1
      ${Loop}

      ${If} $4 != ""
        Call un.NormalizeTrailingSlash
        StrCmp $4 $1 0 keep_segment
          StrCpy $7 "1"        ; 匹配 → 删除该段
          Goto segment_done
        keep_segment:
          ${If} $6 == ""
            StrCpy $6 $4
          ${Else}
            StrCpy $6 "$6;$4"
          ${EndIf}
        segment_done:
      ${EndIf}

      ${If} $3 == ""
        ${ExitDo}
      ${EndIf}
    ${Loop}

    ${If} $7 == "0"
      Return                   ; PATH 中无目标条目 → 无需写回
    ${EndIf}

    ; 剩余为空 → 删除整个 Path 值；否则写回（REG_EXPAND_SZ）
    ${If} $_f33InstallMode == "all"
      ${If} $6 == ""
        DeleteRegValue HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
      ${Else}
        WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" $6
      ${EndIf}
    ${Else}
      ${If} $6 == ""
        DeleteRegValue HKCU "Environment" "Path"
      ${Else}
        WriteRegExpandStr HKCU "Environment" "Path" $6
      ${EndIf}
    ${EndIf}
    Call un.BroadcastEnvChange
  FunctionEnd

  ; 尾部反斜杠归一化（卸载侧副本，un. 前缀）
  Function un.NormalizeTrailingSlash
    Push $5
    Push $6
    ${Do}
      StrLen $5 $4
      ${If} $5 <= 3
        ${ExitDo}
      ${EndIf}
      StrCpy $6 $4 1 -1
      ${If} $6 != "\"
        ${ExitDo}
      ${EndIf}
      StrCpy $4 $4 -1
    ${Loop}
    Pop $6
    Pop $5
  FunctionEnd

  ; WM_SETTINGCHANGE 广播（卸载侧副本，un. 前缀）
  Function un.BroadcastEnvChange
    Push $0
    System::Call 'user32::SendMessageTimeout(i 0xFFFF, i 0x001A, i 0, w "Environment", i 0x0002, i 5000, *i r0)'
    Pop $0
  FunctionEnd
!endif
