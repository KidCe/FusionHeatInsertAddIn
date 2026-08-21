[CmdletBinding()]
param(
    [int]$Port = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$editorPath = Join-Path $root "hardware_library_editor.html"
$libraryPath = Join-Path $root "hardware_library.json"

if (-not (Test-Path -LiteralPath $editorPath -PathType Leaf)) {
    throw "Editor file is missing: $editorPath"
}
if (-not (Test-Path -LiteralPath $libraryPath -PathType Leaf)) {
    throw "Hardware library is missing: $libraryPath"
}

function Get-FreePort {
    $tcpListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $tcpListener.Start()
        return ([int]$tcpListener.LocalEndpoint.Port)
    }
    finally {
        $tcpListener.Stop()
    }
}

function Send-Response {
    param(
        [System.Net.HttpListenerContext]$Context,
        [int]$StatusCode,
        [byte[]]$Body,
        [string]$ContentType
    )

    $Context.Response.StatusCode = $StatusCode
    $Context.Response.ContentType = $ContentType
    $Context.Response.ContentLength64 = $Body.Length
    $Context.Response.OutputStream.Write($Body, 0, $Body.Length)
    $Context.Response.Close()
}

function Send-TextResponse {
    param(
        [System.Net.HttpListenerContext]$Context,
        [int]$StatusCode,
        [string]$Body,
        [string]$ContentType = "text/plain; charset=utf-8"
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    Send-Response -Context $Context -StatusCode $StatusCode -Body $encoding.GetBytes($Body) -ContentType $ContentType
}

function Get-RequestBody {
    param([System.Net.HttpListenerRequest]$Request)

    $memoryStream = [System.IO.MemoryStream]::new()
    try {
        $Request.InputStream.CopyTo($memoryStream)
        return [System.Text.UTF8Encoding]::new($false).GetString($memoryStream.ToArray())
    }
    finally {
        $memoryStream.Dispose()
    }
}

if ($Port -le 0) {
    $Port = Get-FreePort
}

$listener = [System.Net.HttpListener]::new()
$prefix = "http://127.0.0.1:$Port/"
$listener.Prefixes.Add($prefix)

try {
    $listener.Start()
    $url = "$prefix`hardware_library_editor.html"
    Write-Host "Heat Insert Hardware Library Editor"
    Write-Host "Serving the repository on $url"
    Write-Host "This server listens on loopback only. Close this window to stop it."
    Start-Process $url

    while ($listener.IsListening) {
        $context = $listener.GetContext()
        try {
            $path = $context.Request.Url.AbsolutePath
            if ($context.Request.HttpMethod -eq "GET" -and ($path -eq "/" -or $path -eq "/hardware_library_editor.html")) {
                Send-Response -Context $context -StatusCode 200 -Body ([System.IO.File]::ReadAllBytes($editorPath)) -ContentType "text/html; charset=utf-8"
                continue
            }

            if ($path -eq "/hardware_library.json" -and $context.Request.HttpMethod -eq "GET") {
                Send-Response -Context $context -StatusCode 200 -Body ([System.IO.File]::ReadAllBytes($libraryPath)) -ContentType "application/json; charset=utf-8"
                continue
            }

            if ($path -eq "/hardware_library.json" -and $context.Request.HttpMethod -eq "PUT") {
                $body = Get-RequestBody $context.Request
                $null = $body | ConvertFrom-Json
                $temporaryPath = "$libraryPath.tmp-$PID"
                try {
                    $encoding = [System.Text.UTF8Encoding]::new($false)
                    [System.IO.File]::WriteAllBytes($temporaryPath, $encoding.GetBytes($body))
                    Move-Item -LiteralPath $temporaryPath -Destination $libraryPath -Force
                }
                finally {
                    if (Test-Path -LiteralPath $temporaryPath) {
                        Remove-Item -LiteralPath $temporaryPath -Force
                    }
                }
                Send-TextResponse -Context $context -StatusCode 200 -Body '{"saved":true}' -ContentType "application/json; charset=utf-8"
                continue
            }

            Send-TextResponse -Context $context -StatusCode 404 -Body "Not found."
        }
        catch {
            try {
                Send-TextResponse -Context $context -StatusCode 500 -Body $_.Exception.Message
            }
            catch {
                # The client may have disconnected before the error response was sent.
            }
        }
    }
}
finally {
    if ($listener.IsListening) {
        $listener.Stop()
    }
    $listener.Close()
}
