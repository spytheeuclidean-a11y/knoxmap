param(
    [string]$Source = 'output/item14_51x48_source',
    [string]$Destination = 'output/item14_51x48_lots',
    [int]$Threads = 4
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path 'rust/knoxlots/target/release/knoxlots.exe').Path
if (Test-Path $Destination) {
    throw "Destination already exists: $Destination"
}
$log = 'output/item14_51x48_compile_stdout.log'
$err = 'output/item14_51x48_compile_stderr.log'
if ((Test-Path $log) -or (Test-Path $err)) {
    throw 'Benchmark logs already exist; preserve previous results'
}
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $exe -ArgumentList @('compile', $Source, $Destination, '--threads', $Threads) -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -NoNewWindow
$peak = [long]0
do {
    try {
        $running = Get-Process -Id $proc.Id -ErrorAction Stop
        $peak = [math]::Max($peak, [long]$running.WorkingSet64)
        $peak = [math]::Max($peak, [long]$running.PeakWorkingSet64)
    } catch { }
    Start-Sleep -Milliseconds 400
    $proc.Refresh()
} while (-not $proc.HasExited)
$proc.WaitForExit()
$exitCode = $proc.ExitCode
$watch.Stop()
$headers = @(Get-ChildItem $Destination -Filter '*.lotheader' -ErrorAction SilentlyContinue).Count
$result = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    source = $Source
    destination = $Destination
    threads = $Threads
    exit_code = $exitCode
    elapsed_seconds = [math]::Round($watch.Elapsed.TotalSeconds, 3)
    observed_peak_working_set_mib = [math]::Round($peak / 1MB, 1)
    output_lotheaders = $headers
}
$result | ConvertTo-Json | Set-Content 'output/item14_51x48_result.json' -Encoding UTF8
$result | Format-List
if ($exitCode -ne 0) { exit $exitCode }
