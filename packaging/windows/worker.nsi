Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!ifndef APP_VERSION
  !error "APP_VERSION is required"
!endif
!ifndef BUNDLE_DIR
  !error "BUNDLE_DIR is required"
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE is required"
!endif
!define APP_ID "EWasteGridWorker"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
Name "E-Waste Grid Worker ${APP_VERSION} (development)"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\EWasteGridWorker"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID zlib
BrandingText "E-Waste Compute Grid - unsigned team prototype"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "E-Waste Grid Worker"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "CompanyName" "E-Waste Compute Grid Team"
VIAddVersionKey "FileDescription" "Per-user Windows worker installer"
VIAddVersionKey "LegalCopyright" "E-Waste Compute Grid Team"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "NOTICE.txt"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!macro GuardExisting PREFIX
  ; Only an app-owned installation can be upgraded or recursively removed.
  IfFileExists "$INSTDIR\*.*" 0 ${PREFIX}empty
  IfFileExists "$INSTDIR\.ewaste-install-id" 0 ${PREFIX}unsafe
  FileOpen $0 "$INSTDIR\.ewaste-install-id" r
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "${APP_ID}" ${PREFIX}valid ${PREFIX}unsafe
  ${PREFIX}unsafe:
    MessageBox MB_OK|MB_ICONSTOP "This directory is not a verified E-Waste worker install. Choose a clean dedicated location; no files were changed." /SD IDOK
    SetErrorLevel 2
    Quit
  ${PREFIX}valid:
  ${PREFIX}empty:
!macroend

!macro StopOwned PREFIX
  IfFileExists "$INSTDIR\EWasteWorker.exe" 0 ${PREFIX}stopped
  ClearErrors
  ExecWait '"$INSTDIR\EWasteWorker.exe" --shutdown' $0
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "The installed app could not be launched to stop safely. Repair this installation before continuing." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "The worker could not stop safely. Close the app and retry. Installation was not changed." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${PREFIX}stopped:
!macroend

Function .onInit
  SetShellVarContext current
  !insertmacro GuardExisting "install_"
  !insertmacro StopOwned "install_"
FunctionEnd

Section "Worker"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  ; Legacy GUI versions release their lock just before Windows unloads DLLs.
  ; Retry only this verified dependency directory; never overwrite locked files.
  IfFileExists "$INSTDIR\.ewaste-install-id" 0 dependencies_ready
  StrCpy $2 0
  release_dependencies:
    RMDir /r "$INSTDIR\_internal"
    IfFileExists "$INSTDIR\_internal\*.*" 0 dependencies_ready
    IntOp $2 $2 + 1
    ${If} $2 >= 50
      MessageBox MB_OK|MB_ICONSTOP "Windows is still using this app's files. Close the app and retry the installer. User state was retained." /SD IDOK
      SetErrorLevel 3
      Quit
    ${EndIf}
    Sleep 200
    Goto release_dependencies
  dependencies_ready:
  ClearErrors
  File /r "${BUNDLE_DIR}\*.*"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "Could not write the app files. Close owned processes and retry." /SD IDOK
    SetErrorLevel 3
    Quit
  ${EndIf}
  FileOpen $0 "$INSTDIR\.ewaste-install-id" w
  FileWrite $0 "${APP_ID}"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\E-Waste Grid Worker"
  CreateShortcut "$SMPROGRAMS\E-Waste Grid Worker\E-Waste Grid Worker.lnk" "$INSTDIR\EWasteWorker.exe"
  CreateShortcut "$SMPROGRAMS\E-Waste Grid Worker\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "E-Waste Grid Worker"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "E-Waste Compute Grid Team"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ; Login startup is not enabled by installation. A compatible same-path
  ; upgrade retains the owner's existing optional entry.
SectionEnd

Function un.onInit
  SetShellVarContext current
  !insertmacro GuardExisting "uninstall_"
  IfFileExists "$INSTDIR\.ewaste-install-id" +4 0
    MessageBox MB_OK|MB_ICONSTOP "Install identity is missing; refusing cleanup." /SD IDOK
    SetErrorLevel 2
    Quit
  !insertmacro StopOwned "uninstall_"
FunctionEnd

Section "Uninstall"
  ClearErrors
  ExecWait '"$INSTDIR\EWasteWorker.exe" --remove-startup' $0
  ${If} ${Errors}
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Login startup could not be removed safely. Disable it in this install and retry." /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  Delete "$SMPROGRAMS\E-Waste Grid Worker\E-Waste Grid Worker.lnk"
  Delete "$SMPROGRAMS\E-Waste Grid Worker\Uninstall.lnk"
  RMDir "$SMPROGRAMS\E-Waste Grid Worker"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\third_party_notices"
  Delete "$INSTDIR\THIRD_PARTY_INVENTORY.json"
  Delete "$INSTDIR\BUILD_METADATA.json"
  Delete "$INSTDIR\SOURCE_INPUT_HASHES.json"
  Delete "$INSTDIR\EWasteAgent.exe"
  Delete "$INSTDIR\EWasteWorker.exe"
  Delete "$INSTDIR\.ewaste-install-id"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; Per-grid DPAPI state/logs, Docker and shared images are intentionally retained.
SectionEnd
