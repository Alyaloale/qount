param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference = 'Stop'
$base = 'E:\qount_data\qount\datasets\equity_selection\'
$fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
if (-not $fullRoot.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw 'root_outside_E' }
if ([IO.Directory]::Exists($fullRoot)) { throw 'fresh_root_required' }
[IO.Directory]::CreateDirectory($fullRoot) | Out-Null
[Console]::Out.WriteLine('READY')
[Console]::Out.Flush()
while ($null -ne ($line = [Console]::In.ReadLine())) {
    try {
        $item = ConvertFrom-Json -InputObject $line
        $destination = [IO.Path]::GetFullPath([IO.Path]::Combine($fullRoot, [string]$item.name))
        if (-not $destination.StartsWith($fullRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'path_escape' }
        $data = [Convert]::FromBase64String([string]$item.data)
        if ($data.Length -gt 64000000) { throw 'size_budget' }
        $actual = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($data)).ToLowerInvariant()
        if ($actual -ne $item.sha256) { throw 'hash_mismatch' }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        $stream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($data, 0, $data.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        $verify = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($verify -ne $item.sha256) { throw 'stored_hash_mismatch' }
        [Console]::Out.WriteLine($verify)
        [Console]::Out.Flush()
    } catch {
        [Console]::Out.WriteLine('ERROR:' + $_.Exception.GetType().Name)
        [Console]::Out.Flush()
        exit 1
    }
}
