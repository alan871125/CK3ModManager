from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from typing import Generator

def run_multithread(function, iterables, **kwargs):
    thread_kwargs = {k: kwargs.pop(k, None) for k in ['max_workers', 'thread_name_prefix', 'initializer', 'initargs'] if k in kwargs}
    with ThreadPoolExecutor(**thread_kwargs) as executor:
        res = executor.map(lambda x: function(x, **kwargs), iterables)
    return res

def run_multiprocess(function, iterables, **kwargs) -> Generator[Future, None, None]:
    process_kwargs = {k: kwargs.pop(k) for k in ['max_workers', 'mp_context', 'initializer', 'initargs'] if k in kwargs}
    func = partial(function, **kwargs)
    def _generate():
        with ProcessPoolExecutor(**process_kwargs) as executor:
            for item in iterables:
                yield executor.submit(func, item)
    return _generate()