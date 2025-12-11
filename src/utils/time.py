from time import time
import logging

pkg = (__package__ or __name__).split('.')[0]
logger = logging.getLogger(pkg)

def timeit(func):
    """Decorator to measure the execution time of a function."""
    def wrapper(*args, **kwargs):
        start_time = time()
        result = func(*args, **kwargs)
        end_time = time()
        logger.info(f"Function '{func.__name__}' executed in {end_time - start_time:.4f} seconds")
        return result
    return wrapper

def time_execution(func, *args, **kwargs):
    """Function to measure the execution time of a function."""
    def _func(*args, **kwargs):
        start_time = time()
        result = func(*args, **kwargs)
        end_time = time()
        logger.info(f"Function '{func.__name__}' executed in {end_time - start_time:.4f} seconds")
        return result
    return _func(*args, **kwargs)