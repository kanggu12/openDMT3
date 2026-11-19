# The openDMT3 server @VERSION@ on Windows with one command, for this Windows user, without Docker or Python and with
# no administrator's rights:
#
#   irm https://github.com/kanggu12/openDMT3/releases/download/v@VERSION@/opendmt3-server-@VERSION@-windows-installer.ps1 | iex
#
# It takes this release's Windows server package (opendmt3-server-@VERSION@-windows-x64.zip), checked against the
# release's SHA-256 sums (opendmt3-@VERSION@-sha256sums.txt), into %LOCALAPPDATA%\Programs\opendmt3-server
# (OPENDMT3_SERVER_DIR says where), and puts that folder on this user's PATH, so opendmt3-server runs by name in a new
# terminal. The package brings its own Python, the official 7-Zip and the launcher's installer for the Download page;
# the data (accounts, plays, backups, settings) is in its data folder, beside the program, which every version keeps.
# Run again, or a newer release's, it unpacks this version's package first and starts it once (--version), while the
# running server goes on; only then it stops the server it finds running, puts the new program in place, the data
# folder moved into it, and starts it again. A step that fails before the stop (a download, a checksum, a package that
# does not start on this PC) leaves the running server as it was, and says so.
#
#   $env:OPENDMT3_SERVER_UNINSTALL = '1'; irm <the same address> | iex
#       (the server stopped and its firewall rules taken out, the program and its PATH entry removed, the data kept)
#
# Everything runs in a script block of its own: run through iex, the script shares the caller's session, and a
# failure must end the install, not the person's PowerShell window, nor leave settings like ErrorActionPreference
# behind. Windows PowerShell 5.1 runs it, as every Windows 10 and 11 has it.
& {
  $ErrorActionPreference = 'Stop'
  # Windows PowerShell 5.1 speaks only older TLS unless told otherwise.
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

  # The release this script installs: packaging/release_files.py writes it into the copy each release carries.
  $version = '@VERSION@'
  $repo = 'kanggu12/openDMT3'
  # Where the release's files come from; OPENDMT3_SERVER_FILES names a folder of them instead (the install's tests).
  $files = if ($env:OPENDMT3_SERVER_FILES) { $env:OPENDMT3_SERVER_FILES } else { "https://github.com/$repo/releases/download/v$version" }
  $dir = if ($env:OPENDMT3_SERVER_DIR) { $env:OPENDMT3_SERVER_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\opendmt3-server' }
  $dir = $dir.TrimEnd('\')
  $exe = Join-Path $dir 'opendmt3-server.exe'

  function Say([string] $text) { Write-Host $text }
  function Fail([string] $text) { throw "opendmt3-server install: $text" }

  # A program of the package, run with its output on the console (or nowhere, -Quiet), its exit code returned: the
  # output goes to the host, not into what the function returns. Its error output is not turned into PowerShell's
  # errors (Windows PowerShell does that to a native program's standard error under Stop).
  function Run([string] $program, [string[]] $arguments, [switch] $Quiet) {
    $before = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      if ($Quiet) { & $program @arguments *> $null } else { & $program @arguments 2>&1 | Out-Host }
      return $LASTEXITCODE
    } finally {
      $ErrorActionPreference = $before
    }
  }

  # Whether the installed server runs: its status says 0 (it answers) or 1 (it runs and does not answer yet); 3 is
  # none running, as is no program.
  function Running {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return $false }
    $code = Run $exe @('status') -Quiet
    return ($code -eq 0 -or $code -eq 1)
  }

  # This user's PATH, read and written as it is stored, so entries like %USERPROFILE%\bin keep their variables. A
  # PATH stored as a plain string stays one; any other, or a new one, is one Windows expands. $add puts the folder in
  # once; without it the folder is taken out. Windows is told the environment changed, so new terminals see it:
  # setting a variable through .NET sends that message.
  function Set-UserPath([bool] $add) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
      $stored = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
      if ($null -ne $key.GetValue('Path') -and $key.GetValueKind('Path') -eq [Microsoft.Win32.RegistryValueKind]::String) {
        $kind = [Microsoft.Win32.RegistryValueKind]::String
      }
      $entries = @($stored -split ';' | Where-Object { $_ })
      $ours = @($entries | Where-Object { [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -eq $dir })
      if ($add -and $ours.Count -eq 0) {
        $key.SetValue('Path', (@($entries + $dir) -join ';'), $kind)
        Say "added $dir to your PATH: open a new terminal to run opendmt3-server by name"
      } elseif (-not $add -and $ours.Count -gt 0) {
        $key.SetValue('Path', (@($entries | Where-Object { $ours -notcontains $_ }) -join ';'), $kind)
      } else {
        return
      }
      [Environment]::SetEnvironmentVariable('OPENDMT3_SERVER_INSTALLING', '1', 'User')
      [Environment]::SetEnvironmentVariable('OPENDMT3_SERVER_INSTALLING', $null, 'User')
    } finally {
      $key.Close()
    }
  }

  if ($env:OPENDMT3_SERVER_UNINSTALL -eq '1') {
    if (Test-Path -LiteralPath $exe -PathType Leaf) {
      # The server stops by its own command, which also takes out the firewall rules it made (Windows asks for an
      # administrator only when there is one to take out); the data stays.
      $null = Run $exe @('remove')
    }
    # Everything of the program goes; the data folder stays where it is.
    if (Test-Path -LiteralPath $dir) {
      Get-ChildItem -LiteralPath $dir -Force | Where-Object { $_.Name -ne 'data' } | Remove-Item -Recurse -Force
    }
    Set-UserPath $false
    Say "The openDMT3 server is removed. Its data stays in $dir\data (delete that folder to remove it too)."
    return
  }

  if ($version -notmatch '^\d+\.\d+\.\d+') { Fail 'run the copy a release carries (its version is written in)' }
  # The package is for x64; Windows 11 on Arm runs it as it runs every x64 program.
  $machine = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
  if ($machine -ne 'AMD64' -and $machine -ne 'ARM64') { Fail "no package for $machine" }

  # Every file of a release starts with the name, the part and the version, and the zip holds a folder of the same
  # name: opendmt3-server-@VERSION@-windows-x64.
  $name = "opendmt3-server-$version-windows-x64"
  $archive = "$name.zip"
  $sums = "opendmt3-$version-sha256sums.txt"
  $work = Join-Path ([IO.Path]::GetTempPath()) ('opendmt3-server-' + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $work | Out-Null
  try {
    Say "openDMT3 server $version for Windows into $dir"
    # The release's two files: from the folder of them, or downloaded.
    foreach ($file in @($archive, $sums)) {
      if ($files -match '^https?://') {
        try { (New-Object Net.WebClient).DownloadFile("$files/$file", (Join-Path $work $file)) }
        catch { Fail "could not download $files/$file" }
      } else {
        try { Copy-Item -LiteralPath (Join-Path $files $file) -Destination (Join-Path $work $file) }
        catch { Fail "no $file in $files" }
      }
    }
    # The package as the release made it, or nothing at all. Get-FileHash is missing from some PowerShell setups, so
    # the hash is computed directly.
    $line = Get-Content -LiteralPath (Join-Path $work $sums) | Where-Object { $_ -match ('  ' + [regex]::Escape($archive) + '$') } | Select-Object -First 1
    if (-not $line) { Fail "the release's SHA-256 sums name no $archive" }
    $want = ($line -split ' ')[0]
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead((Join-Path $work $archive))
    try { $got = -join ($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) } finally { $stream.Close() }
    if ($got -ne $want) { Fail "$archive is not the release's (its SHA-256 differs): run this again" }

    $wasRunning = Running
    $unchanged = if ($wasRunning) { 'nothing was changed: the server runs as it was' } else { 'nothing was changed' }
    # This version's package unpacked beside the installed one (on the same disk, so putting it in place is a rename),
    # then started once: a package this PC cannot run stops here.
    $parent = Split-Path -Parent $dir
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $incoming = "$dir.incoming"
    if (Test-Path -LiteralPath $incoming) { Remove-Item -LiteralPath $incoming -Recurse -Force }
    # .NET's own zip reader: Windows PowerShell's Expand-Archive takes minutes over the package's thousands of files.
    try {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      [IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $work $archive), $incoming)
    } catch {
      if (Test-Path -LiteralPath $incoming) { Remove-Item -LiteralPath $incoming -Recurse -Force }
      Fail "$archive could not be unpacked ($($_.Exception.Message)); $unchanged"
    }
    $new = Join-Path $incoming $name
    $newExe = Join-Path $new 'opendmt3-server.exe'
    if (-not (Test-Path -LiteralPath $newExe -PathType Leaf)) {
      Remove-Item -LiteralPath $incoming -Recurse -Force
      Fail "$archive holds no $name\opendmt3-server.exe; $unchanged"
    }
    if ((Run $newExe @('--version') -Quiet) -ne 0) {
      Remove-Item -LiteralPath $incoming -Recurse -Force
      Fail "the package does not start on this PC; $unchanged"
    }

    # Now the running server stops, by its own command, and starts again at the end on the new version.
    if ($wasRunning) { $null = Run $exe @('stop') }
    # The installed program is set aside whole, the new one put in its place and the data folder moved into it: put
    # back if that fails, and the old server started again.
    $aside = "$dir.replaced"
    if (Test-Path -LiteralPath $aside) { Remove-Item -LiteralPath $aside -Recurse -Force }
    $had = Test-Path -LiteralPath $dir
    try {
      if ($had) { Move-Item -LiteralPath $dir -Destination $aside }
      Move-Item -LiteralPath $new -Destination $dir
      if ($had -and (Test-Path -LiteralPath (Join-Path $aside 'data'))) {
        Move-Item -LiteralPath (Join-Path $aside 'data') -Destination (Join-Path $dir 'data')
      }
    } catch {
      $why = $_.Exception.Message
      if ($had -and (Test-Path -LiteralPath $aside)) {
        if (Test-Path -LiteralPath (Join-Path $dir 'data')) { Move-Item -LiteralPath (Join-Path $dir 'data') -Destination (Join-Path $aside 'data') }
        if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
        Move-Item -LiteralPath $aside -Destination $dir
        if ($wasRunning) { $null = Run $exe @('start') }
      }
      Fail "the new version could not be put in place in $dir ($why); the old one is back"
    }
    if (Test-Path -LiteralPath $aside) { Remove-Item -LiteralPath $aside -Recurse -Force }
    if (Test-Path -LiteralPath $incoming) { Remove-Item -LiteralPath $incoming -Recurse -Force }
  } finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
  }

  Set-UserPath $true
  $null = Run $exe @('--version')
  if ($wasRunning) { $null = Run $exe @('start') }
  Say ''
  Say 'Next (in a new terminal, or with the whole path):'
  Say '  opendmt3-server setup --admin BOSS   the owner''s account, with the admin pages (its password printed)'
  Say '  opendmt3-server start                the server, in the background'
  Say '  opendmt3-server setup --game PATH    the song list from your client data (a folder or an archive)'
  Say '  opendmt3-server firewall             its ports opened (Windows asks for an administrator''s yes)'
  Say '  opendmt3-server --help               every command'
  Say "The admin pages: http://127.0.0.1:4731/ on this PC. The program: $exe"
}
