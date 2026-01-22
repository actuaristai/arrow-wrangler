"""Module for data tools."""

from collections.abc import Callable
from functools import wraps
from pathlib import Path
from time import time

import ibis
import pandas as pd
import pyarrow as pa  # noqa: F401
import pyarrow.dataset as ds
from ibis import _
from ibis.expr.types.relations import Table
from loguru import logger

ibis.options.interactive = True


class DataTools:
    """Custom methods to add helper data and metadata."""

    @staticmethod
    def get_all_levels(data_con: Table) -> Table:
        """Value Counts summary.

        For all the variables in the DataFrame,
        run value_counts with count and percentages
        and then stack them up into one DataFrame.

        Parameters
        ----------
        data_con : Table
            Table with data to get levels from

        Returns:
        -------
            ibis Table with columns:  level, count, percent, cum_perc,
                                        and column.

        Examples:
        --------
        >>> from arrow_wrangler.data_tools import DataTools
        >>> data = {"A": [1, 2, 1, 1, 2, 2],
        ...        "B": ["a", "b", "a", "a", "b", "c"]}
        >>> result = (DataTools.get_all_levels(ibis.memtable(data))
        ...     .mutate(percent=_['percent'].round(2)))
        >>> result_df = pa.table({"level": ["1", "2", "a", "b", "c"],
        ...                          "count": [3, 3, 3, 2, 1],
        ...                          "variable": ["A", "A", "B", "B", "B"],
        ...                          "percent": [0.5, 0.5, 0.5, 0.33, 0.17]})
        >>> result.to_pyarrow().equals(result_df)
        True
        """
        columns = data_con.columns
        cum_count_freq = None
        for col in columns:
            tot_freq = data_con.count().execute()
            count_freq = data_con \
                .group_by(col) \
                .aggregate(count=_[col].count()) \
                .rename({'level': col}) \
                .mutate(variable=ibis.literal(col)) \
                .cast({'level': 'string'}) \
                .mutate(percent=_['count'] / tot_freq) \
                .order_by([ibis.desc('count'), 'level'])
            cum_count_freq = count_freq if cum_count_freq is None else ibis.union(cum_count_freq, count_freq)
        return cum_count_freq

    @staticmethod
    def read_big_parquet(parquet_location: Path) -> Table:
        """Read parquet file bigger than memory.

        This is for larger than memory dataset
        Uses arrows dataset object
        Note this is different from the pyarrow table object (as used above as default)
        which is using in-memory, so is faster
        Requires duckdb
        This is a bit slower than the in_memory approach (ibis.read_parquet)
        but scales to larger-than-memory datasets!


        Parameters
        ----------
        parquet_location : Path
            path where parquet file is

        Returns:
        -------
        Table
            ibis Table object of parquet file

        Examples:
        --------
        ```python
        from arrow_wrangler.data_tools import DataTools

        MEMBER_DATA = 'data/01_raw/member_data_20221231.parquet'

        dt = DataTools()
        big_data = dt.read_big_parquet(parquet_location=MEMBER_DATA)
        big_data
        ```
        """
        duck = ibis.duckdb.connect()
        pyarrow_ds = ds.dataset(parquet_location)
        return duck.register(pyarrow_ds)

    def timing(self: 'DataTools', f: Callable) -> str:
        """Use as a decorator to print function name and time runs (s) and shape."""

        @wraps(f)
        def wrap(*args: str, **kw: str) -> Callable:
            time_start = time()
            result = f(*args, **kw)
            if isinstance(result, Table):
                row_count = result.count().execute()
                col_count = len(result.schema())
            elif isinstance(result, pd.DataFrame):
                row_count = result.shape[0]
                col_count = result.shape[-1]
            else:
                row_count = 'NA'
                col_count = 'NA'
            time_end = time()
            time_elapsed = time_end - time_start
            logger.info(
                f'func:{f.__name__!r} took:{time_elapsed:2.2f}s, '
                f'dim:({row_count}, {col_count})',
            )
            return result

        return wrap
