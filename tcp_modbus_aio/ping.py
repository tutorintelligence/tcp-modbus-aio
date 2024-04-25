import asyncio
import subprocess


async def ping_ip(ip: str, timeout: float = 0.5) -> float | None:
    """Return the latency in seconds of a ping to the given ip, or None if the ping failed"""
    ping_process = await asyncio.create_subprocess_shell(
        f"ping -c 1 {ip}", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    try:
        # Wait for the subprocess to complete or timeout
        ping_output, stderr = await asyncio.wait_for(
            ping_process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            ping_process.kill()
            await ping_process.wait()
        except ProcessLookupError:
            pass
        return None
    else:
        await ping_process.wait()

    if ping_output is None:
        return None

    try:
        ping_output_str = ping_output.decode("utf-8")
        ping_output_str = ping_output_str.split("\n")[1]
        ping_output_str = ping_output_str.split(" ")[6]
        ping_output_str = ping_output_str.split("=")[1]
        ping_output_latency = float(ping_output_str)
        return ping_output_latency
    except Exception:
        return None
