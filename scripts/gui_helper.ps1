# gui_helper.ps1 - authenticated local HTTP helper for desktop automation.
#
# Runs INSIDE the target interactive session (not Session 0) so it can
# actually touch the desktop. Exposes a tiny local HTTP API on
# 127.0.0.1:<port> for the MoJoAssistant agent bridge to drive the GUI
# without a full RDP / WinAppSDK round-trip.
#
# SECURITY MODEL
# --------------
# 1. Listener binds to 127.0.0.1 ONLY. No LAN exposure.
# 2. Every request must carry `Authorization: Bearer <token>`.
#    Token resolution order:
#       a) $env:MOJO_GUI_TOKEN
#       b) $tokenPath (default ~/.memory/config/gui_helper.token)
#    If neither is set, the helper generates a 32-byte URL-safe token,
#    persists it to $tokenPath (created with chmod-equivalent ACL), and
#    prints it ONCE to the console.
# 3. /launch enforces a strict allowlist loaded from
#    $allowlistPath (default ~/.memory/config/gui_helper.allowlist.json).
#    The file is a JSON array of objects: { "path": "...", "sha256": "..." }
#    sha256 is optional but recommended. Anything outside the allowlist
#    is rejected with 403, even with a valid token.
# 4. /click, /type, /screenshot are gated by token only (no allowlist).
# 5. Request bodies are size-capped (1 MiB) and URLs are URI-decoded once
#    by HttpListenerRequest.QueryString (no manual split/double-decode).
# 6. Process.Start for /launch uses ArgumentList (array), never the
#    `cmd.exe /c` shell, so quoted-argument injection cannot chain
#    commands.
#
# ENDPOINTS
# ---------
#   GET  /health       -> { ok: true, pid: <int> }
#   POST /launch       body: { path: "C:\\Tools\\foo.exe", args: ["a","b"] }
#   POST /click        body: { x: 100, y: 200, button: "left" }
#   POST /type         body: { text: "hello" }
#   GET  /screenshot   -> { bytes_base64: "...", width: ..., height: ... }
#
# LAUNCH
# ------
#   powershell -NoProfile -ExecutionPolicy Bypass -File gui_helper.ps1 `
#       -Port 8766 -TokenPath 'C:\Users\you\.memory\config\gui_helper.token' `
#       -AllowlistPath 'C:\Users\you\.memory\config\gui_helper.allowlist.json'

[CmdletBinding()]
param(
    [int]   $Port           = 8766,
    [string]$TokenPath      = (Join-Path $HOME '.memory\config\gui_helper.token'),
    [string]$AllowlistPath  = (Join-Path $HOME '.memory\config\gui_helper.allowlist.json'),
    [int]   $MaxBodyBytes   = 1MB
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --- 1. Token resolution ------------------------------------------------------

function Get-Or-Create-Token {
    param([string]$Path)
    if ($env:MOJO_GUI_TOKEN) {
        return @{ token = $env:MOJO_GUI_TOKEN; generated = $false }
    }
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        # Best-effort ACL: only the current user can read the token file.
        try {
            $acl = Get-Acl -Path $dir
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $env:USERNAME, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            $acl.SetAccessRule($rule)
            Set-Acl -Path $dir -AclObject $acl
        } catch {
            Write-Warning "Could not tighten ACL on $dir : $_"
        }
    }
    if (Test-Path -LiteralPath $Path) {
        $existing = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
        if ($existing.Length -ge 32) {
            return @{ token = $existing; generated = $false }
        }
    }
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    Set-Content -LiteralPath $Path -Value $token -Encoding UTF8 -NoNewline
    try {
        $fileAcl = Get-Acl -Path $Path
        $fileRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $env:USERNAME, 'FullControl', 'None', 'None', 'Allow')
        $fileAcl.SetAccessRule($fileRule)
        Set-Acl -Path $Path -AclObject $fileAcl
    } catch {
        Write-Warning "Could not tighten ACL on $Path : $_"
    }
    return @{ token = $token; generated = $true }
}

# --- 2. Allowlist -------------------------------------------------------------

function Load-Allowlist {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warning "Allowlist not found at $Path - /launch will reject everything."
        return @()
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        $parsed = $raw | ConvertFrom-Json
    } catch {
        throw "Allowlist at $Path is not valid JSON: $_"
    }
    if ($null -eq $parsed) { return @() }
    if (-not ($parsed -is [System.Collections.IEnumerable])) {
        throw "Allowlist at $Path must be a JSON array of { path, sha256? } objects."
    }
    $norm = @()
    foreach ($entry in $parsed) {
        $p = [string]$entry.path
        if (-not $p) { continue }
        $resolved = [System.IO.Path]::GetFullPath($p)
        $item = [pscustomobject]@{
            path    = $resolved
            sha256  = if ($entry.PSObject.Properties['sha256']) { [string]$entry.sha256 } else { $null }
        }
        $norm += $item
    }
    return $norm
}

function Test-AllowlistMatch {
    param([object[]]$Allowlist, [string]$RequestedPath)
    $resolved = [System.IO.Path]::GetFullPath($RequestedPath)
    foreach ($entry in $Allowlist) {
        if ($entry.path -ne $resolved) { continue }
        if (-not $entry.sha256) { return $true }
        if (-not (Test-Path -LiteralPath $resolved)) { return $false }
        $hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLower()
        return ($hash -eq $entry.sha256.ToLower())
    }
    return $false
}

# --- 3. HTTP plumbing ---------------------------------------------------------

function Write-JsonResponse {
    param([System.Net.HttpListenerResponse]$Response, [int]$Status, [hashtable]$Body)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress -Depth 5))
    $Response.StatusCode = $Status
    $Response.ContentType = 'application/json; charset=utf-8'
    $Response.ContentLength64 = $bytes.Length
    $Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $Response.OutputStream.Close()
}

function Test-Auth {
    param([System.Net.HttpListenerRequest]$Request, [string]$ExpectedToken)
    $header = $Request.Headers['Authorization']
    if (-not $header) { return $false }
    if ($header.Count -lt 1) { return $false }
    $value = [string]$header[0]
    if (-not $value.StartsWith('Bearer ', [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    $presented = $value.Substring(7).Trim()
    if ($presented.Length -ne $ExpectedToken.Length) { return $false }
    # Constant-time compare.
    $a = $presented.ToCharArray()
    $b = $ExpectedToken.ToCharArray()
    $diff = 0
    for ($i = 0; $i -lt $a.Length; $i++) { $diff = $diff -bor ($a[$i] -bxor $b[$i]) }
    return ($diff -eq 0)
}

function Read-BodyJson {
    param([System.Net.HttpListenerRequest]$Request, [int]$MaxBytes)
    if ($Request.ContentLength64 -gt $MaxBytes) { return $null }
    $ms = New-Object System.IO.MemoryStream
    try {
        $Request.InputStream.CopyTo($ms)
    } finally {
        $Request.InputStream.Close()
    }
    if ($ms.Length -gt $MaxBytes) { return $null }
    $text = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
    if ([string]::IsNullOrWhiteSpace($text)) { return @{} }
    try { return ($text | ConvertFrom-Json) } catch { return $null }
}

# --- 4. Endpoint handlers -----------------------------------------------------

function Handle-Health {
    param([System.Net.HttpListenerResponse]$Response)
    Write-JsonResponse -Response $Response -Status 200 -Body @{ ok = $true; pid = $PID }
}

function Handle-Launch {
    param([System.Net.HttpListenerResponse]$Response, $Body, [object[]]$Allowlist)
    $path = [string]$Body.path
    if (-not $path) {
        Write-JsonResponse -Response $Response -Status 400 -Body @{ error = 'missing path' }
        return
    }
    if (-not (Test-AllowlistMatch -Allowlist $Allowlist -RequestedPath $path)) {
        Write-JsonResponse -Response $Response -Status 403 -Body @{ error = 'path not on allowlist'; path = $path }
        return
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-JsonResponse -Response $Response -Status 404 -Body @{ error = 'executable not found'; path = $path }
        return
    }
    $args = @()
    if ($Body.PSObject.Properties['args'] -and $Body.args) {
        foreach ($a in $Body.args) { $args += [string]$a }
    }
    try {
        # Use ArgumentList (array) - never `cmd /c`, never a joined string.
        $proc = Start-Process -FilePath $path -ArgumentList $args -PassThru
        Write-JsonResponse -Response $Response -Status 200 -Body @{
            ok     = $true
            pid    = $proc.Id
            path   = $path
            args   = $args
        }
    } catch {
        Write-JsonResponse -Response $Response -Status 500 -Body @{ error = $_.Exception.Message }
    }
}

function Handle-Click {
    param([System.Net.HttpListenerResponse]$Response, $Body)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $x = [int]$Body.x
    $y = [int]$Body.y
    $button = if ($Body.PSObject.Properties['button']) { [string]$Body.button } else { 'left' }
    $mouseButton = [System.Windows.Forms.MouseButtons]::Left
    if ($button -eq 'right') { $mouseButton = [System.Windows.Forms.MouseButtons]::Right }
    elseif ($button -eq 'middle') { $mouseButton = [System.Windows.Forms.MouseButtons]::Middle }
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($x, $y)
    $signature = @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern void mouse_event(int flags, int dx, int dy, int data, int extra);
'@
    if (-not ([System.Management.Automation.PSTypeName]'Win32').Type) {
        Add-Type -MemberDefinition $signature -Name Win32 -Namespace '' -UsingNamespace System.Runtime.InteropServices
    }
    $down = 0x0002
    $up   = 0x0004
    switch ($mouseButton) {
        'Right'  { $down = 0x0008; $up = 0x0010 }
        'Middle' { $down = 0x0020; $up = 0x0040 }
        default  { $down = 0x0002; $up = 0x0004 }
    }
    [Win32]::mouse_event($down, 0, 0, 0, 0)
    [Win32]::mouse_event($up,   0, 0, 0, 0)
    Write-JsonResponse -Response $Response -Status 200 -Body @{ ok = $true; x = $x; y = $y; button = $button }
}

function Handle-Type {
    param([System.Net.HttpListenerResponse]$Response, $Body)
    Add-Type -AssemblyName System.Windows.Forms
    $text = [string]$Body.text
    # SendKeys uses ^%+{} as control chars. Escape literal occurrences.
    $escaped = $text.Replace('+', '{+}').Replace('^', '{^}').Replace('%', '{%}').Replace('{', '{{}').Replace('}', '{}}')
    [System.Windows.Forms.SendKeys]::SendWait($escaped)
    Write-JsonResponse -Response $Response -Status 200 -Body @{ ok = $true; length = $text.Length }
}

function Handle-Screenshot {
    param([System.Net.HttpListenerResponse]$Response)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    try {
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        try { $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size) }
        finally { $g.Dispose() }
        $ms = New-Object System.IO.MemoryStream
        try {
            $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
            $bytes = $ms.ToArray()
        } finally { $ms.Dispose() }
    } finally {
        $bmp.Dispose()
    }
    $b64 = [Convert]::ToBase64String($bytes)
    Write-JsonResponse -Response $Response -Status 200 -Body @{
        ok      = $true
        width   = $bounds.Width
        height  = $bounds.Height
        bytes_base64 = $b64
    }
}

# --- 5. Boot ------------------------------------------------------------------

$tokenInfo = Get-Or-Create-Token -Path $TokenPath
$Token = $tokenInfo.token
$Allowlist = Load-Allowlist -Path $AllowlistPath

if ($tokenInfo.generated) {
    Write-Host ("[gui_helper] Generated new bearer token and wrote it to {0}" -f $TokenPath)
    Write-Host ("[gui_helper] Token: {0}" -f $Token)
    Write-Host '[gui_helper] Store it as $env:MOJO_GUI_TOKEN on the calling side.'
}
Write-Host ("[gui_helper] Loaded {0} allowlist entries from {1}" -f $Allowlist.Count, $AllowlistPath)
Write-Host ("[gui_helper] Listening on http://127.0.0.1:{0}/  (pid {1})" -f $Port, $PID)

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Clear()
$listener.Prefixes.Add(("http://127.0.0.1:{0}/" -f $Port))
try { $listener.Start() } catch {
    Write-Error "Failed to bind 127.0.0.1:$Port - $_"
    exit 1
}

try {
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $req = $ctx.Request
        $resp = $ctx.Response
        $resp.Headers.Add('X-Content-Type-Options', 'nosniff')
        $resp.Headers.Add('Cache-Control', 'no-store')

        if (-not (Test-Auth -Request $req -ExpectedToken $Token)) {
            Write-JsonResponse -Response $resp -Status 401 -Body @{ error = 'unauthorized' }
            continue
        }

        $path = $req.Url.AbsolutePath.TrimEnd('/')
        $method = $req.HttpMethod
        $body = $null
        if ($method -in @('POST','PUT','PATCH')) {
            $body = Read-BodyJson -Request $req -MaxBytes $MaxBodyBytes
            if ($null -eq $body) {
                Write-JsonResponse -Response $resp -Status 400 -Body @{ error = 'body too large or not valid JSON' }
                continue
            }
        }

        try {
            switch ($path) {
                '/health'     { Handle-Health    -Response $resp }
                '/launch'     { Handle-Launch    -Response $resp -Body $body -Allowlist $Allowlist }
                '/click'      { Handle-Click     -Response $resp -Body $body }
                '/type'       { Handle-Type      -Response $resp -Body $body }
                '/screenshot' { Handle-Screenshot -Response $resp }
                default       { Write-JsonResponse -Response $resp -Status 404 -Body @{ error = 'not found'; path = $path } }
            }
        } catch {
            Write-JsonResponse -Response $resp -Status 500 -Body @{ error = $_.Exception.Message }
        }
    }
} finally {
    if ($listener.IsListening) { $listener.Stop() }
    $listener.Close()
}
