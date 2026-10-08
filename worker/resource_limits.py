"""Shared owner policy validation; RAM is a workload ceiling in GiB."""
import math


def validate_limits(value, cpu_max=64, memory_max=65536):
    if not isinstance(value, dict): raise ValueError('Choose CPU and RAM limits')
    cpu, memory = value.get('cpu'), value.get('memory_gb')
    for amount in (cpu, memory):
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise ValueError('CPU and RAM limits must be finite numbers')
    if not 0.25 <= cpu <= min(64, cpu_max): raise ValueError(f'CPU limit must be between 0.25 and {min(64, cpu_max)}')
    if not 0.25 <= memory <= memory_max: raise ValueError(f'RAM limit must be between 0.25 and {memory_max:g} GiB')
    return {'cpu': float(cpu), 'memory_gb': float(memory)}


def memory_bytes(limits):
    return int(limits['memory_gb'] * 1024 ** 3)
