; Custom NSIS hooks for Agent Flow Harness.
; The Electron app spawns a detached backend process (afh-backend.exe). When the installer
; closes the app it does not always stop that child, and a running afh-backend.exe keeps
; resources\backend\afh-backend.exe locked, so an update silently keeps the OLD backend.
; Kill it before installing and uninstalling so every update actually replaces the backend.

!macro customInit
  nsExec::Exec 'cmd.exe /c taskkill /F /T /IM afh-backend.exe'
  Sleep 300
!macroend

!macro customInstall
  nsExec::Exec 'cmd.exe /c taskkill /F /T /IM afh-backend.exe'
  Sleep 300
!macroend

!macro customUnInstall
  nsExec::Exec 'cmd.exe /c taskkill /F /T /IM afh-backend.exe'
  Sleep 300
!macroend
