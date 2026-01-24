"""Pins functions and ArrowWrangler class for helping with arrow data manipulations."""
from __future__ import annotations

from pathlib import Path
from time import time

import ibis
import pandas as pd  # noqa: F401, RUF100
import pins
import pyarrow as pa
from ibis import _  # noqa: F401
from loguru import logger
from pyarrow.feather import read_table, write_feather

from arrow_wrangler.excel_helper import export_to_excel

ibis.set_backend('duckdb')
ibis.options.interactive = True


class ArrowWrangler:
    """Data Munger using Arrow datasets.

    Examples:
        >>> from pins.data import mtcars
        >>> mtcars_arrow = pa.table(mtcars)
        >>> c = ArrowWrangler(mtcars_arrow)
        >>> c.pipe_ibis(lambda d: d.mutate(x=1)).dataframe
        >>> c.pipe_pandas(lambda d: d.iloc[:, 1:2])
    """

    @classmethod
    def read_from_board(cls: ArrowWrangler, board: pins.boards.BaseBoard, name: str) -> ArrowWrangler | None:
        """Read from board and save it to the object instance's dataframe property.

        Args:
            board (pins.boards.BaseBoard): Pins board to read from.
            name (str): Label for pin.

        Returns:
            ArrowWrangler | None: ArrowWrangler instance with loaded dataframe, or None if pin not found.

        Examples:
            >>> data = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
            >>> table = pa.Table.from_pandas(data)
            >>> aw = ArrowWrangler(table)
            >>> aw.board = pins.board_temp()
            >>> _saved = aw.save_arrow_ifnew(name='simple')
            >>> new = ArrowWrangler.read_from_board(aw.board, 'simple')
            >>> new.dataframe.equals(pa.Table.from_pydict({'a': [1, 2], 'b': [3, 4]}))
            True
        """
        if board.pin_exists(name):
            latest_pin = read_table(board.pin_download(name)[0])
            logger.info(f'dataframe {name} saved into dataframe property')
            return cls(latest_pin, board)

        logger.error(f'board {name} not found')
        return None

    @classmethod
    def read_from_sqlserver(cls: ArrowWrangler,
                            hostname: str,
                            database: str,
                            filter_condition: str | callable | None = None) -> ArrowWrangler:
        """Read from sql server database and initialize new ArrowWrangler object.

        Args:
            hostname (str): String for connecting to mssql.
            database (str): Database.schema.table string.
            filter_condition (str | Callable | None, optional): Either an sql filter condition
                or function to filter/manipulate using sql before saving arrow. Defaults to None.

        Returns:
            ArrowWrangler: ArrowWrangler instance with loaded data.
        """
        catalog, db, table_name = str.split(database, '.')
        con = ibis.mssql.connect(host=hostname,
                                 driver='ODBC Driver 17 for SQL Server',
                                 database=catalog)
        table = con.table(table_name, database=f'{catalog}.{db}')
        if filter_condition is None:
            filtered_table = table
        elif isinstance(filter_condition, str):
            filtered_table = table.sql(filter_condition)
        elif callable(filter_condition):
            filtered_table = filter_condition(table)
        else:
            logger.error('filter_condition must be a string or function or None')
        sql_table_as_arrow = filtered_table.to_pyarrow()
        return cls(sql_table_as_arrow)

    def __init__(self: ArrowWrangler, start_arrow: pa.Table,
                 board: pins.boards.BaseBoard | None = None) -> None:
        """Initialize class from pyarrow table.

        Args:
            start_arrow (pa.Table): Arrow table to load into object's dataframe property.
            board (pins.boards.BaseBoard or None, optional): Board to save and read data from.
                Defaults to None, which creates a temporary board.
        """
        self.dataframe = start_arrow
        if board is not None:
            self.board = board
        else:
            self.board = pins.board_temp()

    def __repr__(self: ArrowWrangler) -> str:
        """Show ibis output with columns and rowcount.

        Returns:
            str: String representation of the dataframe with shape information.
        """
        shape = self.dataframe.shape
        return f'{ibis.memtable(self.dataframe).__repr__()} \n\n rows: {shape[0]} \n columns: {shape[1]}'

    @property
    def board(self: ArrowWrangler) -> pins.boards.BaseBoard:
        """Get board.

        Returns:
            The pins board instance.
        """
        return self._board

    @board.setter
    def board(self: ArrowWrangler, board: pins.boards.BaseBoard) -> pins.boards.BaseBoard:
        """Set board.

        Args:
            board: Pins board instance to set.
        """
        if isinstance(board, pins.boards.BaseBoard):
            self._board = board
        else:
            logger.error('Please set pins board type')

    @property
    def dataframe(self: ArrowWrangler) -> pa.Table:
        """Get dataframe.

        Returns:
            The pyarrow table instance.
        """
        return self._dataframe

    @dataframe.setter
    def dataframe(self: ArrowWrangler, arrow: pa.Table) -> pa.Table:
        """Set dataframe.

        Args:
            arrow: Pyarrow table to set.
        """
        if isinstance(arrow, pa.Table):
            self._dataframe = arrow
        else:
            logger.error('Please set a pyarrow table')

    def pipe_arrow(self: ArrowWrangler,
                   func: callable,
                   *args: tuple,
                   other_datasets: list | None = None,
                   **kwargs: dict) -> ArrowWrangler:
        """Apply a function to the ArrowWrangler object in a chain-able manner.

        Args:
            func: Function to apply. Must have input pa.Table and return pa.Table.
            *args: Arguments that will be passed to the function.
            other_datasets: List of strings defining the names of data pins to read.
                The string names must match the function parameter names.
            **kwargs: Keyword-arguments that will be passed to the function.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> from pins.data import mtcars
            >>> mtcars_arrow = pa.table(mtcars)
            >>> c = ArrowWrangler(mtcars_arrow)
            >>> mpg_cyl = c.pipe_arrow(lambda d: d.select(['cyl', 'mpg']))
            >>> mpg_cyl.dataframe.shape
            (32, 2)
        """
        time_start = time()

        # base functionality with piping of function with pa.Table as input and pa.Table as output
        if other_datasets is None:
            self.dataframe = func(self.dataframe, *args, **kwargs)

        # functionality for reading and piping other datasets
        elif isinstance(other_datasets, list):
            other_arrow_dict = {}
            for _i, other_ds_name in enumerate(other_datasets):
                logger.debug(other_ds_name)
                if isinstance(other_ds_name, str):
                    if self.board.pin_exists(other_ds_name):
                        other_arrow_dict[other_ds_name] = self.read_from_board(self.board, other_ds_name).dataframe
                    else:
                        logger.error(f'pin {other_ds_name} could not be found')
                else:
                    logger.error('`other_datasets` need to be a list of strings')
            try:
                pipe_result = func(self.dataframe, *args, **other_arrow_dict, **kwargs)
                if isinstance(pipe_result, pa.Table):
                    self.dataframe = pipe_result
                else:
                    logger.error('Function you are piping to needs to return a pa.Table')
            except TypeError:
                argument_helper = ''
                for _key, value in enumerate(other_arrow_dict):
                    argument_helper = argument_helper + f'{value}: pa.Table, '
                logger.error(f'Syntax Error with pipe function \n \
                               Need to construct piped function properly. \n \
                               Match up the parameters and the piped argument names. \n \
                               Expecting piped function to have {len(other_datasets)} \n \
                               argument names in piped function. \n \
                               Needs to include: {argument_helper}')

        else:
            logger.error('Expect other_datasets argument needs to be None or list of strings representing board names')

        # logging time and data shape
        row_count = self.dataframe.shape[0]
        col_count = self.dataframe.shape[1]
        time_end = time()
        time_elapsed = time_end - time_start
        logger.info(f'func:{func.__name__!r} took:{time_elapsed:2.2f}s, '
                    f'dim:({row_count}, {col_count})')
        return self

    def pipe_ibis(self: ArrowWrangler,
                  func: callable,
                  *args: tuple,
                  other_datasets: list | None = None,
                  **kwargs: dict) -> ArrowWrangler:
        """Apply formula taking input ibis table and output ibis table.

        Automatically convert from pyararow before function, and back to pyarrow after function.

        Args:
            func: Function to apply. Function must have input ibis.memtable and return ibis.memtable.
            *args: Arguments that will be passed to the function.
            other_datasets: List of strings defining the names of data pins to read from the board.
                If this is used, the name of the string needs to be the name of the parameter that the function is passed
                to. eg if pipe_arrow has other_datasets=['cobe', 'bp'], then this needs to be the other datasets
                def pass_functions(initial_tbl: ibis.expr.types.Table,
                                   year: int,
                                   cobe: ibis.expr.types.Table,
                                   bp: ibis.expr.types.Table):
                    return initial_tbl
            **kwargs: Keyword-arguments that will be passed to the function.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> import ibis
            >>> from ibis import _
            >>> from pins.data import mtcars
            >>> mtcars_arrow = pa.table(mtcars)
            >>> c = ArrowWrangler(mtcars_arrow)
            >>> half_mpg = c.pipe_ibis(lambda d: d.mutate(half_mpg=_['mpg'] / 2))
            >>> half_mpg.dataframe.shape
            (32, 12)
        """
        time_start = time()

        # base functionality with piping of function with ibis.memtable as input and ibis.memtable as output
        ibis_table = ibis.memtable(self.dataframe)
        if other_datasets is None:
            self.dataframe = func(ibis_table, *args, **kwargs).to_pyarrow()

        # functionality for reading and piping other datasets
        elif isinstance(other_datasets, list):
            other_arrow_dict = {}
            other_arrow_dict_ibis = {}
            for _i, other_ds_name in enumerate(other_datasets):
                logger.debug(other_ds_name)
                if isinstance(other_ds_name, str):
                    if self.board.pin_exists(other_ds_name):
                        other_arrow_dict[other_ds_name] = self.read_from_board(self.board, other_ds_name).dataframe
                        other_arrow_dict_ibis[other_ds_name] = ibis.memtable(other_arrow_dict[other_ds_name])
                    else:
                        logger.error(f'pin {other_ds_name} could not be found')
                else:
                    logger.error('`other_datasets` need to be a list of strings')
            try:
                pipe_result = func(ibis_table, *args, **other_arrow_dict_ibis, **kwargs)
                if isinstance(pipe_result, ibis.expr.types.Table):
                    self.dataframe = pipe_result.to_pyarrow()
                else:
                    logger.error('Function you are piping to needs to return an ibis table')
            except TypeError:
                argument_helper = ''
                for _key, value in enumerate(other_arrow_dict_ibis):
                    argument_helper = argument_helper + f'{value}: ibis.expr.types.Table, '
                logger.error(f'Syntax Error with pipe function \n \
                               Need to construct piped function properly. \n \
                               Match up the parameters and the piped argument names. \n \
                               Expecting piped function to have {len(other_datasets)} \n \
                               argument names in piped function. \n \
                               Needs to include: {argument_helper}')

        else:
            logger.error('Expect other_datasets argument needs to be None or list of strings representing board names')

        # logging time and data shape
        row_count = self.dataframe.shape[0]
        col_count = self.dataframe.shape[1]
        time_end = time()
        time_elapsed = time_end - time_start
        logger.info(f'func:{func.__name__!r} took:{time_elapsed:2.2f}s, '
                    f'dim:({row_count}, {col_count})')
        return self

    def pipe_pandas(self: ArrowWrangler,
                    func: callable,
                    *args: tuple,
                    other_datasets: list | None = None,
                    **kwargs: dict) -> ArrowWrangler:
        """Apply formula taking input pandas DataFrame and output pandas DataFrame.

        Automatically convert from pyararow before function, and back to pyarrow after function.

        Args:
            func: Function to apply. Function must input pd.DataFrame and return pd.DataFrame.
            *args: Arguments that will be passed to the function.
            other_datasets: List of strings defining the names of data pins to read from the board.
                If this is used, the name of the string needs to be the name of the parameter that the function is passed
                to. eg if pipe_arrow has other_datasets=['cobe', 'bp'], then this needs to be the other datasets
                def pass_functions(initial_tbl: pd.DataFrame,
                                   year: int,
                                   cobe: pd.DataFrame,
                                   bp: pd.DataFrame):
                    return initial_tbl
            **kwargs: Keyword-arguments that will be passed to the function.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> from pins.data import mtcars
            >>> mtcars_arrow = pa.table(mtcars)
            >>> c = ArrowWrangler(mtcars_arrow)
            >>> mpg_wt = c.pipe_pandas(lambda d: d.loc[:, ['mpg', 'wt']])
            >>> mpg_wt.dataframe.column_names
            ['mpg', 'wt']
            >>> concat = mpg_wt.save_arrow_ifnew('mtcars_mpg_wt').pipe_pandas(
            ...     lambda d, mtcars_mpg_wt: pd.concat([d, mtcars_mpg_wt]), other_datasets=['mtcars_mpg_wt'])
            >>> concat.dataframe.shape[0] == mtcars.shape[0] * 2
            True
        """
        time_start = time()

        # base functionality with piping of function with pd.Table as input and pd.Table as output
        pd_table = self.dataframe.to_pandas()
        if other_datasets is None:
            self.dataframe = pa.table(func(pd_table, *args, **kwargs))

        # functionality for reading and piping other datasets
        elif isinstance(other_datasets, list):
            other_arrow_dict = {}
            other_arrow_dict_pd = {}
            for _i, other_ds_name in enumerate(other_datasets):
                logger.debug(other_ds_name)
                if isinstance(other_ds_name, str):
                    if self.board.pin_exists(other_ds_name):
                        other_arrow_dict[other_ds_name] = self.read_from_board(self.board, other_ds_name).dataframe
                        other_arrow_dict_pd[other_ds_name] = other_arrow_dict[other_ds_name].to_pandas()
                    else:
                        logger.error(f'pin {other_ds_name} could not be found')
                else:
                    logger.error('`other_datasets` need to be a list of strings')
            try:
                pipe_result = func(pd_table, *args, **other_arrow_dict_pd, **kwargs)
                if isinstance(pipe_result, pd.DataFrame):
                    self.dataframe = pa.table(pipe_result)
                else:
                    logger.error('Function you are piping to needs to return an pandas DataFrame')
            except TypeError:
                argument_helper = ''
                for _key, value in enumerate(other_arrow_dict_pd):
                    argument_helper = argument_helper + f'{value}: pd.DataFrame, '
                logger.error(f'Syntax Error with pipe function \n \
                               Need to construct piped function properly. \n \
                               Match up the parameters and the piped argument names. \n \
                               Expecting piped function to have {len(other_datasets)} \n \
                               argument names in piped function. \n \
                               Needs to include: {argument_helper}')
        else:
            logger.error('Expect other_datasets argument needs to be None or list of strings representing board names')

        # logging time and data shape
        row_count = self.dataframe.shape[0]
        col_count = self.dataframe.shape[1]
        time_end = time()
        time_elapsed = time_end - time_start
        logger.info(f'func:{func.__name__!r} took:{time_elapsed:2.2f}s, '
                    f'dim:({row_count}, {col_count})')
        return self

    def pipe_sql(self: ArrowWrangler,
                 sql_text: str,
                 input_tbl_name: str = 'me',
                 other_datasets: list | None = None) -> ArrowWrangler:
        """Apply formula using sql via duckdb (tsql dialect).

        Creates a view called 'me' to read sql from

        Automatically convert form pyararow before function, and back to pyarrow after function.

        Args:
            sql_text: SQL script to run.
            input_tbl_name: Name to get table alias eg so you can use SELECT * FROM me. Defaults to 'me'.
            other_datasets: List of strings defining the names of data pins to read from the board.
                This is used to create a duckdb view with that name to be able to query using sql.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> from pins.data import mtcars
            >>> import pyarrow.compute as pc
            >>> mtcars_arrow = pa.table(mtcars)
            >>> c = ArrowWrangler(mtcars_arrow)
            >>> cyl4 = c.pipe_sql('select * from me where cyl == 4')
            >>> pc.max(cyl4.dataframe['cyl'])
            <pyarrow.Int64Scalar: 4>
            >>> union = cyl4.save_arrow_ifnew('car_cyl4').pipe_sql(
            ...  'select * from car_cyl4 union all select * from me', other_datasets=['car_cyl4'])
            >>> union.dataframe.shape[0] == mtcars.query('cyl == 4').shape[0] * 2
            True
        """
        time_start = time()

        # set up duckdb connection to be able to run sql commands
        con = ibis.duckdb.connect()
        con.create_view(input_tbl_name, ibis.memtable(self.dataframe))

        # read other_datasets into the duckdb connection as a view
        if isinstance(other_datasets, list):
            for _i, other_ds_name in enumerate(other_datasets):
                logger.debug(other_ds_name)
                if isinstance(other_ds_name, str):
                    if self.board.pin_exists(other_ds_name):
                        read_other_ds = self.read_from_board(self.board, other_ds_name).dataframe
                        con.create_view(other_ds_name, ibis.memtable(read_other_ds))
                    else:
                        logger.error(f'pin {other_ds_name} could not be found')
                else:
                    logger.error('need to be a list of strings for other_datasets')
        elif other_datasets is None:
            pass
        else:
            logger.error('other_datasets argument needs to be a list of strings or None')

        # run the script using tsql dialect
        self.dataframe = con \
            .sql(sql_text,
                 dialect='tsql') \
            .to_pyarrow()

        # log the shape and runtime
        row_count = self.dataframe.shape[0]
        col_count = self.dataframe.shape[1]
        time_end = time()
        time_elapsed = time_end - time_start
        logger.info(f'pipe_sql took:{time_elapsed:2.2f}s, '
                    f'dim:({row_count}, {col_count})')
        return self

    def save_arrow_ifnew(self: ArrowWrangler, name: str) -> None:
        """Save arrow table to a board if it is new file (different to latest board pin).

        Save to board property of object.

        Args:
            name: Label for pin.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> data = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
            >>> table = pa.Table.from_pandas(data)
            >>> aw = ArrowWrangler(table)
            >>> aw.board = pins.board_temp()
            >>> _saved = aw.save_arrow_ifnew(name='simple')
            >>> aw.board.pin_versions('simple').count()==1
            created    True
            hash       True
            version    True
            dtype: bool
        """
        if self.board.pin_exists(name):
            latest_pin = read_table(self.board.pin_download(name)[0])
            if latest_pin.equals(self.dataframe):
                logger.info('data is the same, not rewriting')
            else:
                logger.info('updating data')
                Path('data/temp').mkdir(parents=True, exist_ok=True)
                write_feather(self.dataframe, f'data/temp/{name}.feather')
                self.board.pin_upload(f'data/temp/{name}.feather', name)
        else:
            logger.info('writing new data')
            Path('data/temp').mkdir(parents=True, exist_ok=True)
            write_feather(self.dataframe, f'data/temp/{name}.feather')
            self.board.pin_upload(f'data/temp/{name}.feather', name)
        return self

    def save_excel(self: ArrowWrangler, name: str, sheet: str) -> None:
        """Save arrow table to a board if it is new file (different to latest board pin).

        Save to board property of object.

        Args:
            name: Label for pin (and spreadsheet).
            sheet: Name of the Excel sheet.

        Returns:
            ArrowWrangler instance with updated dataframe property.

        Examples:
            >>> data = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
            >>> table = pa.Table.from_pandas(data)
            >>> aw = ArrowWrangler(table)
            >>> aw.board = pins.board_temp()
            >>> _save = aw.save_arrow_ifnew(name='simple')
            >>> aw.board.pin_versions('simple').count()==1
            created    True
            hash       True
            version    True
            dtype: bool
        """
        if self.board.pin_exists(name):
            latest_pandas = pd.read_excel(self.board.pin_download(name)[0], skiprows=1)
            latest_pin = pa.table(latest_pandas)
            if latest_pin.equals(self.dataframe):
                logger.info('data is the same, not rewriting')
            else:
                logger.info('updating data')
                export_to_excel(self.dataframe.to_pandas(), f'data/temp/{name}.xlsx', sheet)
                self.board.pin_upload(f'data/temp/{name}.xlsx', name)
        else:
            logger.info('writing new data')
            export_to_excel(self.dataframe.to_pandas(), f'data/temp/{name}.xlsx', sheet)
            self.board.pin_upload(f'data/temp/{name}.xlsx', name)
        return self
