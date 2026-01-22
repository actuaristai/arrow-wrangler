"""Excel export with metadata."""
import os
import subprocess
from datetime import datetime

import pandas as pd
import xlwings as xw
from loguru import logger


def export_to_excel(df: pd.DataFrame, file_name: str, sheet_name: str) -> None:
    """Use xlwings to export and format data with timestamp.

    Parameters
    ----------
    df : pd.DataFrame
        data to export
    file_name : str
        filename and path to export
    sheet_name : str
        sheet name. also becomes table name
    """
    login = os.getlogin()
    user = subprocess.check_output(['whoami', '/fqdn']).strip().decode()  # noqa: S607
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # noqa: DTZ005
    git_hash = subprocess.check_output(['git', 'describe', '--always']).strip().decode()  # noqa: S607
    git_remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin']).strip().decode()  # noqa: S607

    # Check if the Excel file already exists
    if not os.path.exists(file_name):  # noqa: PTH110
        # If the workbook does not exist, create a new one
        xw.Book().save(file_name)
        with xw.Book(file_name) as book:
            sheet = book.sheets.add(sheet_name)

    # Use context manager to handle the workbook
    with xw.Book(file_name) as book:
        # Get the sheet, if it does not exist, add it
        try:
            sheet = book.sheets[sheet_name]
        except Exception as e:  # noqa: BLE001
            exception_name = type(e).__name__
            logger.debug(f'Caught exception: {exception_name}')
            logger.info(f'adding in sheet {sheet_name}')
            sheet = book.sheets.add(sheet_name)

        # Write the user name and timestamp to the first cell
        metadata = ('User Name: ' + user + login + ', ' +
                    'Export Time: ' + timestamp + ', ' +
                    'File: ' + __file__ + ', ' +
                    'git hash: ' + git_hash + ', ' +
                    'git remote: ' + git_remote)
        sheet.range('A1').value = metadata

        # Write the dataframe to the Excel file, starting from the second row
        sheet.range('A2').value = df
        sheet.range('A1').font.color = (0, 0, 255)  # blue
        sheet.tables.add(source=sheet['A2'].expand(), name=sheet_name)
        book.save()
