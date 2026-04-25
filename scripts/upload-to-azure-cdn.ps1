# Upload static assets to Azure Storage + optional CDN endpoint purge
param(
    [string]$ResourceGroup = "smdg-prod",
    [string]$StorageAccount = "smdgcdn",
    [string]$ContainerName = "static",
    [string]$CDNProfileName = "smdg-cdn-profile",
    [string]$CDNEndpointName = "smdg"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$staticDir = Join-Path $root "static"

if (-not (Test-Path $staticDir)) {
    Write-Error "Directory not found: $staticDir"
}

Write-Host "Uploading to Azure Storage ($StorageAccount) / $ContainerName ..."

$ctx = New-AzStorageContext -StorageAccountName $StorageAccount -UseConnectedAccount

Get-ChildItem -Path $staticDir -Recurse -File | ForEach-Object {
    $relativePath = $_.FullName.Substring($staticDir.Length + 1)
    $blobName = $relativePath -replace "\\", "/"

    $cacheControl = if ($_.Extension -in ".html") {
        "no-cache, no-store, must-revalidate"
    } elseif ($_.Name -eq "manifest.json") {
        "public, max-age=300"
    } elseif ($_.Extension -in ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico") {
        "public, max-age=2592000"
    } else {
        "public, max-age=31536000, immutable"
    }

    Set-AzStorageBlobContent -File $_.FullName `
        -Container $ContainerName `
        -Blob $blobName `
        -Context $ctx `
        -Properties @{CacheControl = $cacheControl} `
        -Force | Out-Null
}

try {
    Write-Host "Purging CDN endpoint $CDNEndpointName ..."
    Publish-AzCdnEndpointContent `
        -ResourceGroupName $ResourceGroup `
        -ProfileName $CDNProfileName `
        -EndpointName $CDNEndpointName `
        -ContentPath @("/*")
} catch {
    Write-Warning "CDN purge skipped: $_"
}

Write-Host "Done."
