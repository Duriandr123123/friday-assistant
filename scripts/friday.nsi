Unicode True
!include "MUI2.nsh"
Name "Пятница"
OutFile "..\dist\Friday-Setup-0.4.0.exe"
InstallDir "$LOCALAPPDATA\Programs\FridayAssistant"
RequestExecutionLevel user
SetCompressor zlib
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"

Section "Пятница"
  SetOutPath "$INSTDIR"
  File /r "..\dist\Friday\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FridayAssistant" "DisplayName" "Пятница"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FridayAssistant" "DisplayVersion" "0.4.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FridayAssistant" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  IfSilent no_shortcuts
  CreateDirectory "$SMPROGRAMS\Пятница"
  CreateShortcut "$SMPROGRAMS\Пятница\Пятница.lnk" "$INSTDIR\Friday.exe"
  CreateShortcut "$DESKTOP\Пятница.lnk" "$INSTDIR\Friday.exe"
  no_shortcuts:
SectionEnd

Section "Uninstall"
  !include "..\.tools\friday-uninstall.nsh"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\Пятница\Пятница.lnk"
  RMDir "$SMPROGRAMS\Пятница"
  Delete "$DESKTOP\Пятница.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FridayAssistant"
SectionEnd
