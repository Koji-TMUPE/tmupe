import matplotlib
matplotlib.use('TkAgg')

import argparse
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider, CheckButtons, TextBox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import tkinter as tk
from tkinter import messagebox, ttk
import pandas as pd
import numpy as np
import os, re, copy
import csv
import matplotlib.backends.backend_tkagg as tkagg
from functools import partial

# local modules
from tkerror import show_on_error
from TkinterScrollableFrame import ScrollableFrame

# Tk for messagebox
#tk_root = tk.Tk()
#tk_root.withdraw()

version_CsvPlotter = 'v2.3.2'

class FileProcessor:
    def __init__(self):
        self.processed_data = {}
        self.metadata= []
        self.file_paths = {}

    def sanitize_path(self, path):
        """
        Sanitize Windows-style file paths to Python format.

        - Parameters
        --path: (str) File or directory path that may contain backslashes.

        - Returns
        -- (str) Sanitized path using forwared slashes.

        - Examples
        >>> sanitize_path("C:\\Users\\Koji")
        'C:/Users/Koji'
        """

        return path.strip().strip('"').replace("\\", "/")

    def setPath(self, input_paths):
        input_paths = input_paths.split(',')
        self.file_paths = [self.sanitize_path(path) for path in input_paths]

        if len(self.file_paths) == 1 and os.path.isdir(self.file_paths[0]):
            directory = self.file_paths[0]
            self.file_paths = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(('.csv', '.txt', '.tsv'))]
        return self.file_paths

    def _is_numeric(self, val):
        try:
            float(val)
            return True
        except:
            return False

    def _decode_file(self, file_path):
        """Read text file robustly against encoding issues (e.g., cp932/cp931 errors).

        Strategy:
        - Read as bytes and try multiple common encodings.
        - Fall back to 'utf-8' with replacement so that the program keeps running.
        """
        with open(file_path, 'rb') as fb:
            raw = fb.read()

        for enc in ('utf-8-sig', 'utf-8', 'cp932', 'shift_jis', 'latin-1'):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError:
                continue

        # Last resort
        return raw.decode('utf-8', errors='replace'), 'utf-8'

    def _sniff_delimiter(self, sample_lines):
        """Detect delimiter (comma/tab/etc.) using csv.Sniffer with a safe fallback."""
        sample = ''.join(sample_lines[:50])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[',','\t',';','|'])
            return dialect.delimiter
        except Exception:
            # heuristic fallback
            if '\t' in sample:
                return '\t'
            return ','

    def _split_fields(self, line, delimiter):
        fields = [v.rstrip() for v in line.strip().split(delimiter)]
        # ignore trailing empty fields caused by extra delimiters
        while len(fields) > 0 and fields[-1] == '':
            fields.pop()
        return fields

    def _estimate_data_nfields(self, lines, start_row, delimiter, max_scan=50):
        """Estimate the real number of columns in data region (ignore metadata lines with extra delimiters)."""
        nmax = 0
        scanned = 0
        for i in range(start_row, min(len(lines), start_row + max_scan)):
            fields = self._split_fields(lines[i], delimiter)
            if len(fields) == 0:
                continue
            nmax = max(nmax, len(fields))
            scanned += 1
        return nmax if nmax > 0 else None

    def _detect_metadata_and_header(self, lines, delimiter):
        count_numeric = 0
        countmax_numeric = 3
        metadata_end_row = -1
        header_row = -1
        for i, line in enumerate(lines):
            values = self._split_fields(line, delimiter)

            # header candidate: any field contains alphabetic character
            if any(any(ch.isalpha() for ch in v) for v in values):
                header_row = i

            # numeric line candidate: all fields numeric (or empty)
            if len(values) > 0 and all(self._is_numeric(v) or v == '' for v in values):
                count_numeric += 1
                if count_numeric >= countmax_numeric:
                    break
            else:
                count_numeric = 0

            if count_numeric == 0:
                metadata_end_row = i
        return metadata_end_row, header_row

    def _detect_empty_columns(self, lines, metadata_end_row, delimiter):
        """Legacy helper.
        NOTE: In v2.3.1 we prefer usecols based on the actual data column count.
        This remains for backward compatibility but is not relied upon.
        """
        count_empty_col = 0
        countmax_empty_col = 10
        buf_null_num = None
        for i, line in enumerate(lines):
            if i > metadata_end_row:
                values = self._split_fields(line, delimiter)
                if len(values) == 0:
                    continue
                null_num = values.count('')
                if buf_null_num is not None and buf_null_num == null_num:
                    count_empty_col += 1
                else:
                    count_empty_col = 0
                if count_empty_col >= countmax_empty_col:
                    return null_num
                buf_null_num = null_num
        return -1

    def input_text_cui(self):
        input_paths = input("Enter file paths (comma-separated) or a directory path: ").split(',')
        self.file_paths = [self.sanitize_path(path) for path in input_paths]

        if len(self.file_paths) == 1 and os.path.isdir(self.file_paths[0]):
            directory = self.file_paths[0]
            self.file_paths = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(('.csv', '.txt', '.tsv'))]
        return self.file_paths
        
    def load_csvs(self):
        try:
            for self.file_path in self.file_paths:
                self.file_path = self.sanitize_path(self.file_path)

                file_text, enc = self._decode_file(self.file_path)
                lines = file_text.splitlines(True)

                delimiter = self._sniff_delimiter(lines)
                metadata_end_row, header_row = self._detect_metadata_and_header(lines, delimiter)

                filename = os.path.basename(self.file_path)
                if metadata_end_row >= 0:
                    metadata = lines[:metadata_end_row + 1]
                    self.metadata.append({"file": filename, "metadata": metadata})
                else:
                    self.metadata.append({"file": filename, "metadata": []})

                # Determine where data starts and the expected number of fields in data region.
                # This avoids failures when metadata lines contain extra delimiters (extra commas/tabs).
                data_start_row = max(metadata_end_row + 1, (header_row + 1) if header_row >= 0 else (metadata_end_row + 1))
                nfields = self._estimate_data_nfields(lines, data_start_row, delimiter)

                # Read with pandas using robust options
                skiprows = metadata_end_row + 1 if metadata_end_row >= 0 else 0
                header = None
                if header_row >= 0 and header_row > metadata_end_row:
                    header = header_row - skiprows

                read_kwargs = dict(
                    sep=delimiter,
                    engine='python',
                    encoding=enc,
                    skiprows=skiprows,
                    header=header,
                    on_bad_lines='skip'
                )

                if header is None and nfields is not None:
                    read_kwargs['header'] = None
                    read_kwargs['names'] = [f'column_{i+1}' for i in range(nfields)]
                    read_kwargs['usecols'] = list(range(nfields))
                elif nfields is not None:
                    # keep only columns that really exist in the data region
                    read_kwargs['usecols'] = list(range(nfields))

                df = pd.read_csv(self.file_path, **read_kwargs)

                # If header was detected but resulted in numeric-like column names, fallback to generic names
                if read_kwargs.get('header', None) is not None:
                    try:
                        if all(self._is_numeric(str(col)) for col in df.columns):
                            df.columns = [f"column_{i+1}" for i in range(df.shape[1])]
                    except Exception:
                        pass

                # Drop fully-empty columns
                df = df.dropna(how='all', axis=1)

                # Ensure time/index column
                if df.shape[1] >= 1:
                    df.iloc[:, 0] = pd.to_numeric(df.iloc[:, 0], errors='coerce')
                    df = df.dropna(subset=[df.columns[0]])
                    df.set_index(df.columns[0], inplace=True)

                self.process_data(df, filename)

        except Exception as e:
            print(f"Error processing {self.file_paths}: {e}")


    def process_data(self, dataframe, filename='dataframe'):
        try:
            label = [f"{filename} - {col}" for col in dataframe.columns]
            self.processed_data[filename] = {'data': dataframe, 'label': label}
            print(os.path.basename(self.file_path))
            
        except Exception as e:
            print(f"Error processing {self.file_paths}: {e}")

    def display_metadata(self):
        for entry in self.metadata:
            print(f"Metadata for {entry['file']}:\n{''.join(entry['metadata']) if entry['metadata'] else 'No metadata detected.'}")



class CsvPlotter():

    FILTER_NONE: str = 'None'
    FILTER_1stOrderLPF: str = '1st Order LPF'
    FILTER_1stOrderHPF: str = '1st Order HPF'

    def __init__(self, processed_data=None, screens=None):

        ## the numbers related to CsvPlotter list variables
        ##
        ## num_files: the number of files the users can specify
        ## num_linesInFile: the number of lines in each file
        ## num_lines: the number of lines in all files
        ## num_axes: =num_rows x num_columns, the number of screen by matrix format
        ## num_rows: the number of screen rows
        ## num_columns: the number of screen columns
        ## num_offset: =num_files, the offsets for each files
        ## num_slider: =num_files, the sliders for offset
        ## num_filter =num_lines, the sliders for offset
        ## num_xmin: =num_columns, the x axis range for each column
        ## num_xmax: =num_columns, the x axis range for each column
        ## num_ymin: =num_columns, the y axis range for each column
        ## num_ymax: =num_columns, the y axis range for each column
        ## num_default_xlim: = num_rows, the tuple of default xmin and xmax.
        ## num_default_ylim: num_rows, the tuple of default xmin and xmax.
        ## num_legend: =num_lines, the number of all lines

        ## label definition: label = f"{file} - {col}", file is the filename (df_info['file']), col is the header label of the dataframe
                    
        self.processed_data_matrix = None    # list (screen_row, screen_col) of dict ({'filename 1', 'filename 2', ...}) of dict (processed_data from FileProcessor), ['index']: the index of file numbers, ['data']: the data of the filename, ['label']: the list (the number of channels = df_info.['data'].columns()) of the data label, ['original_x']: the original time numbers for each file, ['lines']: the list (the number of channels) of the matplotlib plot axes
        self.xlim = {}  # list (screen_row, screen_col) of list [xmin, xmax]
        self.default_xlim = {}  # list (screen_row, screen_col) of list [default xmin, default xmax]
        self.ylim = {}  # list (screen_row, screen_col) of list [ymin, ymax]
        self.default_ylim = {}  # list (screen_row, screen_col) of list [default ymin, default ymax]
#        self.original_times = {}    # list ([screen_rows, screen_columns]) of dict, [label]: the original time data of the labeled file. The label is formatted as f'{filename} - {col}' (for label, line in self.lines: if label.startswith(file):).
#        self.offsets = {}   # list ([screen_rows, screen_columns]) of dict, [label]: the time offset for each lines. #['file']: time offset for each files, 1 dim list with elements of the num of files (for df_info in self.dataframes --> self.offsets[df_info['file']]).
#        self.lines = {} # list ([screen_rows, screen_columns]) of dict, [label]: the ax.plot (ax.plot(df.index, df[col], label=label)).
        self.filter_method = {} # list ([screen_rows, screen_columns]) of dist, [label]: the filtering method for each lines, 
        self.filter_cutoff = {} # list ([screen_rows, screen_columns]) of dist, [label]: the filter cutoff freqneyc,
        self.reset_button = None    # to be omitted
        self.output_button = None   # to be omitted
        self.legend = None
        self.xmin = {}  # list [screen_rows]
        self.xmax = {} # list [screen_rows]
        self.ymin = {} # list [screen_rows]
        self.ymax = {} # list [screen_rows]
        self.default_xlim = {}  # list [screen_rows] of tuple (xmin, xmax)
        self.default_ylim = {}  # list [screen_rows] of tuple (ymin, ymax)
        self.screen_rows = 0    # int, the number of screen rows
        self.screen_columns = 0 # int, the number of screen columns
#        self.label = {} # this can be replaced by dataframe['label']. the label for each line used to specify the line.
        self.ax = None  # list, [self,screen_rows, self.screen_columns], each element is a matplot axes.
        self.fig = None # matplot fig. Only one object exists in this program.

        if screens != None:
            self.setFigAxes(screens)
        
        if processed_data!= None:
            self.setProcesseddatamatrix(processed_data)

    @show_on_error
    def getScreenRowCol(self):
        return [self.screen_rows, self.screen_columns]

    @show_on_error
    def setProcesseddatamatrix(self, processed_data):
        if self.screen_rows == 0:
            print(f'Set the screen matrix before setting processed_data.')
            exit(1)

        print(f'sc rows: {self.screen_rows}, sc columns: {self.screen_columns}')
        self.processed_data_matrix = [
                [copy.deepcopy(processed_data) for _ in range(self.screen_columns)]
                for _ in range(self.screen_rows)
                ]
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
#                print(f'rows: {row}, columns: {col}')
#                self.processed_data_matrix[row][col] = processed_data 

                # create the data to be edited
                for filename in self.processed_data_matrix[row][col].keys():
                    self.processed_data_matrix[row][col][filename]['editdata'] = processed_data[filename]['data']

    @show_on_error
    def setFigAxes(self, screens=None, screen_rows=1, screen_columns=1):
        try:
            self.screen_rows, self.screen_columns = map(int, screens.replace('x',' ').split()) if len(screens) > 0 else [1,1]
        except Exception as e:
            print(e)
            self.screen_rows=screen_rows
            self.screen_columns=screen_columns

        self.fig, self.ax = plt.subplots(self.screen_rows, self.screen_columns, figsize=(10, 6), squeeze=False)
#        self.fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.98)
        self.fig.tight_layout()
        print(self.ax)
        print(self.ax[0][0])
        print(self.ax[0][0].get_xlim())
#        self.ax = self.ax.flatten() if self.screen_rows * self.screen_columns > 1 else [self.ax]
#        print(f'self.ax: {self.ax}')


    # [ The remaining methods like plot(), plot_lines(), add_sliders(), etc. go here unchanged. ]
    @show_on_error
    def plot(self, show=False):

        # set the dataframe and screen matrix, and get the fix and axes
        if self.processed_data_matrix == None: # if no  processed_data set, return False
            return False
        if self.screen_rows == 0 or self.screen_columns == 0:   # if no screen matrix set, use the default
            self.screen_rows = 1
            self.screen_columns = 1
            self.setFigAxes()

#        self.fig.subplots_adjust(left=0.3, bottom=0.45)

        # set Labels (default = filename - column label
        self._initLabels()

        # set original time
        self._initOriginalX()
        self._initOriginalY()

        # set filters (default = None)
        self._initFilter()

        # set offsets (default = 0)
        self._initXOffsets()
        self._initYOffsets()

        # set the x and y range
#        self._initXYlim()

        # set the plot lines (set the plot lines to axes for each screen)
        self._initLines()

        # add legend on the plot to be omitted
#        self._add_plot_list()

        # add additional features to be omitted
#        self.add_sliders()
#        self.add_filter_controls()
#        self.add_reset_button()
#        self.add_output_button()
#        self.add_axis_range_boxes()
#        self.fig.canvas.mpl_connect('button_press_event', self._on_press)
#        self.fig.canvas.mpl_connect('motion_notify_event', self._on_motion)
#        self.fig.canvas.mpl_connect('button_release_event', self._on_release)

        # show the plot
        if show == True:
            plt.show()

        return True

    @show_on_error
    def _initOriginalX(self):#, processed_data):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for processed_data in self.processed_data_matrix[row][col].values():
                    processed_data['original_x'] =  processed_data['data'].index.to_numpy() # set the original times

    @show_on_error
    def getOriginalX(self, row, col, filename):
        return self.processed_data_matrix[row][col][filename]['original_x']


    @show_on_error
    def _initOriginalY(self):#, processed_data):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]['data']
                    labels = self.processed_data_matrix[row][col][filename]['label']
                    self.processed_data_matrix[row][col][filename]['original_y'] = {}
                    self.processed_data_matrix[row][col][filename]['filtered_y'] = {}
                    self.processed_data_matrix[row][col][filename]['filter_method'] = {}
                    self.processed_data_matrix[row][col][filename]['filter_cutoff'] = {}
                    i=0
                    for colname in df.columns:
                        yraw = df[colname].to_numpy()
                        self.processed_data_matrix[row][col][filename]['original_y'][labels[i]] = yraw
                        self.processed_data_matrix[row][col][filename]['filtered_y'][labels[i]] = yraw
                        self.processed_data_matrix[row][col][filename]['filter_method'][labels[i]] = 'N/A'
                        self.processed_data_matrix[row][col][filename]['filter_cutoff'][labels[i]] = 0.0
                        i+=1

# [row][col]-> {'filename1': {'data': df, 'label': labels}, 'filename2': {'data': df, 'label': labels}}

    @show_on_error
    def getOriginalY(self, row, col, filename, label):
        return self.processed_data_matrix[row][col][filename]['original_y'][label]

    @show_on_error
    def getFilenames(self, row, col):
        filenames = self.processed_data_matrix[row][col].keys()
        return filenames

    @show_on_error
    def getIndexOfLabels(self, row, col, filename, label):
        labels = self.processed_data_matrix[row][col][filename]['label']
        for index, target_label in labels.items():
            if label == target_label:
                return index
        return None

    @show_on_error
    def getLabels(self, row, col, filename):
        labels = self.processed_data_matrix[row][col][filename]['label']
        return labels

    @show_on_error
    def setLabels(self, row, col, filename, labels):
        self.processed_data_matrix[row][col][filename]['label'] = labels

    @show_on_error
    def _initLabels(self):#, processed_data):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]["data"]
                    i=0
                    label = {}
                    for colname in df.columns:
                        label[i] = f"{colname} - {filename}"   # set the default label
                        i+=1
                    self.processed_data_matrix[row][col][filename]['label'] = label

    @show_on_error
    def _initLines(self):#, processed_data, row][col):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]['editdata']
                    label = self.processed_data_matrix[row][col][filename]['label']
                    i=0
                    lines = {}
                    for colname in df.columns:
                        lines[label[i]] = self.ax[row][col].plot(df.index, df[colname], label=label[i])  # add the lines to plot in axes
                        i+=1

                    self.processed_data_matrix[row][col][filename]['lines'] = lines

    @show_on_error
    def setVisibility(self, row, col, filename, label, visibility):
        self.processed_data_matrix[row][col][filename]['lines'][label][0].set_visible(visibility)
        self.updateDraw()

    @show_on_error
    def getVisibility(self, row, col, filename, label):
        return self.processed_data_matrix[row][col][filename]['lines'][label][0].get_visible()

    @show_on_error
    def setXOffsets(self, row, col, filename, offsets):
        self.processed_data_matrix[row][col][filename]['xoffsets'] = offsets

    @show_on_error
    def setYOffsets(self, row, col, filename, offsets):
        self.processed_data_matrix[row][col][filename]['yoffsets'] = offsets

    @show_on_error
    def setXOffset(self, row, col, filename, label, offset):
        self.processed_data_matrix[row][col][filename]['xoffsets'][self.getIndexOfLabels(row,col,filename,label)] = offset
        original_x = self.getOriginalX(row, col, filename)
#        y = self.processed_data_matrix[row][col][filename]['lines'][label][0].get_ydata()

        self.processed_data_matrix[row][col][filename]['lines'][label][0].set_xdata(original_x + offset)
        self.updateDraw()

    @show_on_error
    def setYOffset(self, row, col, filename, label, offset):
        self.processed_data_matrix[row][col][filename]['yoffsets'][self.getIndexOfLabels(row,col,filename,label)] = offset
        ybase = self.processed_data_matrix[row][col][filename].get('filtered_y', {}).get(label, self.getOriginalY(row, col, filename, label))
        self.processed_data_matrix[row][col][filename]['lines'][label][0].set_ydata(ybase + offset)
        self.updateDraw()

    @show_on_error
    def getFilter(self, row, col, filename, label):
        method = self.processed_data_matrix[row][col][filename]['filter_method'].get(label, 'N/A')
        cutoff = self.processed_data_matrix[row][col][filename]['filter_cutoff'].get(label, 0.0)
        return method, cutoff

    @show_on_error
    def setFilter(self, row, col, filename, label, method, cutoff):
        # store
        self.processed_data_matrix[row][col][filename]['filter_method'][label] = method
        try:
            cutoff_val = float(cutoff)
        except Exception:
            cutoff_val = 0.0
        self.processed_data_matrix[row][col][filename]['filter_cutoff'][label] = cutoff_val

        # recompute filtered_y from original_y
        x = self.getOriginalX(row, col, filename)
        if x is None or len(x) < 2:
            dt = None
        else:
            dx = np.diff(x)
            dx = dx[np.isfinite(dx)]
            dx = dx[dx > 0]
            dt = float(np.median(dx)) if dx.size > 0 else None

        yraw = self.getOriginalY(row, col, filename, label)
        yflt = self.apply_filter(yraw, dt, method, cutoff_val)
        self.processed_data_matrix[row][col][filename]['filtered_y'][label] = yflt

        # apply y-offset immediately on the line
        yoff = self.getYOffset(row, col, filename, label)
        self.processed_data_matrix[row][col][filename]['lines'][label][0].set_ydata(yflt + yoff)
        self.updateDraw()

    @show_on_error
    def getXOffsets(self, row, col, filename):
        return self.processed_data_matrix[row][col][filename]['xoffsets']

    @show_on_error
    def getYOffsets(self, row, col, filename):
        return self.processed_data_matrix[row][col][filename]['yoffsets']

    @show_on_error
    def getXOffset(self, row, col, filename, label):
        return self.processed_data_matrix[row][col][filename]['xoffsets'][self.getIndexOfLabels(row,col,filename,label)]

    @show_on_error
    def getYOffset(self, row, col, filename, label):
        return self.processed_data_matrix[row][col][filename]['yoffsets'][self.getIndexOfLabels(row,col,filename,label)]

    @show_on_error
    def _initXOffsets(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]['data']
                    label = self.processed_data_matrix[row][col][filename]['label']
                    i=0
                    offsets = {}
                    for colname in df.columns:
                        offsets[i] = 0
                        i+=1
                    self.processed_data_matrix[row][col][filename]['xoffsets'] = offsets

    @show_on_error
    def _initYOffsets(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]['data']
                    label = self.processed_data_matrix[row][col][filename]['label']
                    i=0
                    offsets = {}
                    for colname in df.columns:
                        offsets[i] = 0
                        i+=1
                    self.processed_data_matrix[row][col][filename]['yoffsets'] = offsets

    @show_on_error
    def setFilters(self, row, col, file, filters):
        self.processed_data_matrix[row][col][file]['filters'] = filters

    @show_on_error
    def _initFilter(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                for filename in self.processed_data_matrix[row][col].keys():
                    df = self.processed_data_matrix[row][col][filename]['data']
                    label = self.processed_data_matrix[row][col][filename]['label']
                    i=0
                    filters = {}
                    for colname in df.columns:
                        filters[i] = CsvPlotter.FILTER_NONE
                        i+=1
                    self.processed_data_matrix[row][col][filename]['filters'] = filters

    @show_on_error
    def resetXlim(self, row, col):
        self.xlim[row][col] = self.default_xlim[row][col]
        self.ax[row][col].set_xlim(self.xlim[row][col])
#        self.processed_data_matrix[row][col]['xlim'] = self.processed_data_matrix[row][col]['default_xlim']

    @show_on_error
    def resetXlimAll(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                self.resetXlim(row,col)

    @show_on_error
    def getXlim(self, row, col):
        xmin, xmax = self.ax[row][col].get_xlim()
        return xmin, xmax
        

    @show_on_error
    def setXlim(self, row, col, xlim):
        xmin, xmax = xlim
        self.xlim[row][col] = (float(xmin), float(xmax))
        self.ax[row][col].set_xlim(xlim)
#        self.processed_data_matrix[row][col]['xlim'] = xlim

    @show_on_error
    def resetYlim(self, row, col):
        self.ylim[row][col] = self.default_ylim[row][col]
        self.ax[row][col].set_ylim(self.ylim[row][col])
#        self.processed_data_matrix[row][col]['ylim'] = self.processed_data_matrix[row][col]['default_ylim']

    @show_on_error
    def resetYlimAll(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                self.resetYlim(row,col)

    @show_on_error
    def getYlim(self, row, col):
        ymin, ymax = self.ax[row][col].get_ylim()
        return ymin, ymax

    @show_on_error
    def setYlim(self, row, col, ylim):
        ymin, ymax = ylim
        self.ylim[row][col] = (float(ymin), float(ymax))
        self.ax[row][col].set_ylim(self.ylim[row][col])
#        self.processed_data_matrix[row][col]['ylim'] = ylim

    @show_on_error
    def _initXYlim(self):    
        self.default_xlim = [[0]*self.screen_columns]*self.screen_rows
        self.default_ylim = [[0]*self.screen_columns]*self.screen_rows
        self.xlim = [[0]*self.screen_columns]*self.screen_rows
        self.ylim = [[0]*self.screen_columns]*self.screen_rows
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                self.default_xlim[row][col] = self.ax[row][col].get_xlim()    # axes.get_xlim returns (left, right) of the current x-asix view.
                self.default_ylim[row][col] = self.ax[row][col].get_ylim()    # axes.get_ylim returns (left, right) of the current y-asix view.
#                self.processed_data_matrix[row][col]['default_xlim'] = self.ax[row][col].get_xlim()    # axes.get_xlim returns (left, right) of the current x-asix view.
#                self.processed_data_matrix[row][col]['default_ylim'] = self.ax[row][col].get_ylim()    # axes.get_xlim returns (left, right) of the current x-asix view.
                self.setXlim(row,col, self.default_xlim[row][col])
                self.setYlim(row,col, self.default_ylim[row][col])
#                self.setXlim(row][col, self.processed_data_matrix[row][col]['default_xlim'])
#                self.setYlim(row][col, self.processed_data_matrix[row][col]['default_ylim'])


    @show_on_error
    def _add_plot_list(self):
        for row in range(self.screen_rows):
            for col in range(self.screen_columns):
                labels = list(self.processed_data_matrix[row][col][filename]['label'] for filename in self.processed_data_matrix[row][col].keys())
                visibility = [True] * len(labels)
#                self.check_buttons_ax = plt.axes([0.01, 0.4, 0.25, 0.5])
#                self.check_buttons = CheckButtons(self.check_buttons_ax, labels, visibility)
                self.dragging = False
                self.drag_start = None


    @show_on_error
    def updateDraw(self):
        self.fig.canvas.draw_idle()


    ########################################################## old version

    @show_on_error
    def apply_filter(self, ydata, dt, method, cutoff):
        """Simple 1st-order IIR LPF/HPF.

        method: 'N/A', '1st-LPF', '1st-HPF'
        cutoff: Hz
        """
        if method in (None, 'N/A') or cutoff is None or cutoff <= 0 or dt is None or dt <= 0:
            return ydata

        y = np.asarray(ydata, dtype=float)
        if y.size == 0:
            return y

        rc = 1.0 / (2.0 * np.pi * float(cutoff))
        if rc <= 0:
            return y

        if method == '1st-LPF':
            alpha = dt / (rc + dt)
            out = np.empty_like(y)
            out[0] = y[0]
            for i in range(1, y.size):
                out[i] = out[i-1] + alpha * (y[i] - out[i-1])
            return out

        if method == '1st-HPF':
            alpha = rc / (rc + dt)
            out = np.empty_like(y)
            out[0] = 0.0
            for i in range(1, y.size):
                out[i] = alpha * (out[i-1] + y[i] - y[i-1])
            return out

        return y

    @show_on_error
    def add_filter_controls(self):
        start = 0.25
        method_list = [
                "N/A",
                "1st order LPF",
                "1st order HPF"
                ]
        for i, df_info in enumerate(self.dataframes):
            file = df_info["file"]

            filter_ax = plt.axes([0.64, start - i * 0.05, 0.1, 0.03])
            combo = TextBox(filter_ax, "", initial='N/A')
            self.filter_dropdowns[file] = combo

            cutoff_ax = plt.axes([0.77, start - i * 0.05, 0.07, 0.03])
            cutoff_box = TextBox(cutoff_ax, "", initial="0.0")
            self.filter_cutoff_boxes[file] = cutoff_box
            prop_bbox=dict(boxstyle='round', facecolor='white', alpha=0.15)
            self.fig.text(0.65, start+0.05, "Filter", bbox=prop_bbox)
            self.fig.text(0.77, start+0.05, "f_cutoff", bbox=prop_bbox)



class GUI_start(tk.Tk):
    @show_on_error
    def __init__(self, *args, **kwargs):
        self.path = ''
        self.thin = 1
        self.screen = ''

        ### Layer declaration ###
        ### layer 0 ###
        tk.Tk.__init__(self, *args, **kwargs)
        self.title("CSV plotter initialization")

        # set protocol in exitting
        self.protocol('WM_DELETE_WINDOW', lambda :self.quit_me())
        

    @show_on_error
    def bind_returnPath(self, widget_1, widget_2):
#        len_text = len(widget_1.get())
        widget_2.focus()
        try:
            widget_2.icursor(65535)
        except Exception as e:
            pass 

    @show_on_error
    def button_command(self):
        self.path = self.widgetL2[1].get()
        self.thin = self.widgetL2[3].get()
        self.screen = self.widgetL2[5].get()
        print(self.path)
        print(self.thin)
        print(self.screen)
        self.quit_me()

    @show_on_error
    def quit_me(self):
        self.quit()
        self.destroy()

    @show_on_error
    def show_me(self):
        self.widgetL2[1].focus()    # focus the first entry widget
        self.tkraise()
        self.mainloop()

    @show_on_error
    def setFrame(self):
        ### layer 1 ###
        self.frameL1 = {}
        self.frameL1[0] = tk.Frame(self)
        self.frameL1[1] = tk.Frame(self)
        self.frameL1[2] = tk.Frame(self)
        self.frameL1[3] = tk.Frame(self)

        ### layer 2 ###
        self.widgetL2 = {}
        self.widgetL2[0] = tk.Label(self.frameL1[0], text='File/directory path',width=50)
        self.widgetL2[1] = tk.Entry(self.frameL1[0], width=50)
        self.widgetL2[1].bind("<Return>", lambda x: self.bind_returnPath(self.widgetL2[1],self.widgetL2[3]))

        self.widgetL2[2] = tk.Label(self.frameL1[1], text='The number of thinned data',width=50)
        self.widgetL2[3] = tk.Entry(self.frameL1[1], width=50)
        self.widgetL2[3].bind("<Return>", lambda x: self.bind_returnPath(self.widgetL2[3],self.widgetL2[5]))

        self.widgetL2[4] = tk.Label(self.frameL1[2], text='The grid of screens (rows x cols)',width=50)
        self.widgetL2[5] = tk.Entry(self.frameL1[2], width=50)
        self.widgetL2[5].bind("<Return>", lambda x: self.bind_returnPath(self.widgetL2[5],self.widgetL2[6]))

        self.widgetL2[6] = tk.Button(self.frameL1[3], width=50, text='OK', command=lambda :self.button_command())
        self.widgetL2[6].bind("<Return>", lambda x: self.button_command())

        ## layer 2 placing ##
        self.widgetL2[0].grid(row=0, column=0)
        self.widgetL2[1].grid(row=0, column=1)
        self.widgetL2[2].grid(row=0, column=0)
        self.widgetL2[3].grid(row=0, column=1)
        self.widgetL2[4].grid(row=0, column=0)
        self.widgetL2[5].grid(row=0, column=1)
        self.widgetL2[6].grid(row=0, column=0)

        ## layer 1 placing ##
        self.frameL1[0].grid(row=0, column=0)
        self.frameL1[1].grid(row=1, column=0)
        self.frameL1[2].grid(row=2, column=0)
        self.frameL1[3].grid(row=3, column=0)

        # show window
#        self.show_frame()
#        self.tkraise()
        self.widgetL2[1].focus()    # focus the first entry widget
#        self.mainloop()


class GUI_plotter(tk.Tk):
    path_icon = "C:/Users/Koji Mitsui/OneDrive/Incorperate/06_ToolsForEngineer/0000_CsvPlotter/11_Figs/meldes.ico" 

    @show_on_error
    def __init__(self, *args, **kwargs):
        # initial declaration
        self.pane = {} # layer 0
        self.framePlot = {} # layer 1
        self.frameOpts = {} # layer 1
        self.frameBot = {} # layer 1
        self.frameXaxis = {} # layer 1
        self.canvas = {} # layer 2
        self.frameOpt = {} # layer 2
        self.frameSync = {} # layer 2
        self.entry_Xmin = {} # layer 3
        self.entry_Xmax = {} # layer 3
        self.label_Xmin = {} # layer 3
        self.label_Xmax = {} # layer 3
        self.frameYlim = {} # layer 3
        self.frameLegend = {} # layer 3
        self.frameXOffset = {} # layer 3
        self.frameYOffset = {} # layer 3
        self.frameFilter = {} # layer 3
        self.frameCutoff= {} # layer 3
        self.entry_Ymin = {} # layer 4
        self.entry_Ymax = {} # layer 4
        self.label_Ymin = {} # layer 4
        self.label_Ymax = {} # layer 4
        self.check_Legend = {} # layer 4
        self.entry_XOffset = {} # layer 4
        self.entry_YOffset = {} # layer 4
        self.combo_Filter = {} # layer 4
        self.entry_Cutoff = {} # layer 4
        self.label_Screen = {}
        self.label_Legend = {}
        self.label_XOffset = {}
        self.label_YOffset = {}
        self.label_Filter = {}
        self.label_Cutoff = {}
        self.var_check_Legend = {} # layer 4
        self.var_entry_XOffset = {}
        self.var_entry_YOffset = {}
        self.var_entry_Cutoff = {}
        self.var_combo_Filter = {}
        self.check_syncFilter = {} # layer 3
        self.check_syncXOffset = {} # layer 3
        self.check_syncYOffset = {} # layer 3
        self.button_reset = {} # layer 3
        self.group = {}
        self.canvas_width = 1000
        self.canvas_height = 1000
        self.plotter = None #CsvPlotter()

        self.screen_rows = None
        self.screen_columns = None

        # variables
        self.xslider_min = -1
        self.xslider_max = 1

        self.var_check_syncFilter = None
        self.var_check_syncXOffset = None
        self.var_check_syncYOffset = None
        self.var_value_Xlim = None

        self._xlim_change_row = None
        self._xlim= None
        self._xlim_change_col = None

        self._width_yentry = 9
        self._width_xentry = 9
        self._width_xoffsetentry = 9
        self._width_yoffsetentry = 9
        self._width_cutoffentry = 9

        self._combo_filter_types = {}

        ### layer 0 ###
        tk.Tk.__init__(self, *args, **kwargs)
        self.title(f"CsvPlotter")  # option
#        self.geometry("400x300") # option
#        self.withdraw() # option
        self.protocol('WM_DELETE_WINDOW', lambda :self.quit_me())

        self.vcmd = (self.register(self._is_valid_float), '%P')
        self._disable_combobox_wheel_globally()

    @show_on_error
    def tkInit(self):
        print('tkinit')

    @show_on_error
    def _disable_combobox_wheel_globally(self):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            # 本体のホイール無効（ttkのクラス名）
            self.bind_class("TCombobox", seq, lambda e: "break")
            # 互換（古い/環境差対策）
            self.bind_class("Combobox",  seq, lambda e: "break")
            # ポップダウン(Listbox)側も無効化
            self.bind_class("Listbox",   seq, lambda e: "break")

    @show_on_error
    def show_me(self):
        self._init_XYlim_entry_from_plot()  # this line should be reconsidered to place proper line.
       
        self.iconbitmap(default=self.path_icon)
        self.tkraise()
        self.mainloop()

    @show_on_error
    def show_frame(self, cont):
        frame = self.frames[cont]
        frame.tkraise()

    @show_on_error
    def quit_me(self):
        self.quit()
        self.destroy()

    @show_on_error
    def _forward_wheel_to_opts(self, event):
        """
        コンボボックス上のホイールを、左ペイン（self.frameOpts）のスクロールに流す。
        """
        canvas = getattr(self.frameOpts, "canvas", None)
        if not canvas:
            return "break"

        try:
            # Windows/mac: event.delta > 0 で上スクロール、< 0 で下スクロール
            # Linux: Button-4（上）/Button-5（下）
            if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
                canvas.yview_scroll(-1, "units")
            else:
                canvas.yview_scroll(1, "units")
        except Exception:
            pass
        return "break"

#    @show_on_error
#    def create_combo(self, frame, dropdown_list, height, width):
#        cb = ttk.Combobox(frame, values=dropdown_list, state="readonly", height=height, width=width)
#        cb.set("N/A")
##        cb.place(x=x, y=y)
#        return cb

    @show_on_error
    def _combo_filter_NA(self):
        pass

    @show_on_error
    def _combo_filter_1stLPF(self):
        print(f'filter: {self._combo_filter.keys()[1]}')
        pass

    @show_on_error
    def _combo_filter_1stHPF(self):
        print(f'filter: {self._combo_filter.keys()[2]}')
        pass

    @show_on_error
    def _init_combo_filter(self):
        self._combo_filter_types = {'N/A': self._combo_filter_NA, '1st-LPF': self._combo_filter_1stLPF, '1st-HPF': self._combo_filter_1stHPF}

    @show_on_error
    def _combo_filter_changed(self, event=None):
        # Apply selected filter per line
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                k = 0
                for filename in self.plotter.getFilenames(i, j):
                    for label in self.plotter.getLabels(i, j, filename).values():
                        method = self.var_combo_Filter[i][j][k].get()
                        cutoff = self._get_corrected_float(self.entry_Cutoff[i][j][k].get())
                        if cutoff is None:
                            cutoff = 0.0
                        cur_method, cur_cutoff = self.plotter.getFilter(i, j, filename, label)
                        if method != cur_method or float(cutoff) != float(cur_cutoff):
                            self.plotter.setFilter(i, j, filename, label, method, cutoff)
                        k += 1

    @show_on_error
    def setCsvPlotter(self, plotter):
        print('set csv plotter')
        self.plotter = plotter

#    def setCsvPlotter(self, dataframes, screen):
#        print('set csv plotter')
#        self.plotter = CsvPlotter(dataframes)#, screen)
#        self.plotter.setFigAxes(screen)
#        self.plotter.plot(show=False)

    def _update_xoffset(self, event=None):
        # Validate user input before calling plotter setters.
        # If input is invalid, show a single user-facing popup and revert the entry to the previous value.
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                k = 0
                for filename in self.plotter.getFilenames(i, j):
                    for label in self.plotter.getLabels(i, j, filename).values():
                        raw = self.var_entry_XOffset[i][j][k].get()
                        value_offset = self._get_corrected_float(raw)
                        if value_offset is None:
                            try:
                                import tkinter.messagebox as messagebox
                                messagebox.showerror("Input error", f"Invalid X offset: '{raw}'. Please enter a valid number (e.g., 1, -0.5, 1e-3).")
                            except Exception:
                                pass
                            # revert to current offset
                            self.var_entry_XOffset[i][j][k].set(str(self.plotter.getXOffset(i, j, filename, label)))
                            k += 1
                            continue

                        cur = self.plotter.getXOffset(i, j, filename, label)
                        if float(value_offset) != float(cur):
                            self.plotter.setXOffset(i, j, filename, label, float(value_offset))
                        k += 1


    def _update_yoffset(self, event=None):
        # Validate user input before calling plotter setters.
        # If input is invalid, show a single user-facing popup and revert the entry to the previous value.
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                k = 0
                for filename in self.plotter.getFilenames(i, j):
                    for label in self.plotter.getLabels(i, j, filename).values():
                        raw = self.var_entry_YOffset[i][j][k].get()
                        value_offset = self._get_corrected_float(raw)
                        if value_offset is None:
                            try:
                                import tkinter.messagebox as messagebox
                                messagebox.showerror("Input error", f"Invalid Y offset: '{raw}'. Please enter a valid number (e.g., 1, -0.5, 1e-3).")
                            except Exception:
                                pass
                            # revert to current offset
                            self.var_entry_YOffset[i][j][k].set(str(self.plotter.getYOffset(i, j, filename, label)))
                            k += 1
                            continue

                        cur = self.plotter.getYOffset(i, j, filename, label)
                        if float(value_offset) != float(cur):
                            self.plotter.setYOffset(i, j, filename, label, float(value_offset))
                        k += 1


    @show_on_error
    def get_entry_value_Xmin(self, event=None):
        for i in range(self.screen_columns):
            min_value = self._get_corrected_float(self.entry_Xmin[i].get())
            max_value = self._get_corrected_float(self.entry_Xmax[i].get())
            if min_value == None or max_value == None:
                return None
            xlim = (min_value, max_value)
            for j in range(self.screen_rows):
                self.plotter.setXlim(j, i, xlim)
        self.plotter.updateDraw()

    @show_on_error
    def get_entry_value_Xmax(self, event=None):
        for i in range(self.screen_columns):
            min_value = self._get_corrected_float(self.entry_Xmin[i].get())
            max_value = self._get_corrected_float(self.entry_Xmax[i].get())
            if min_value == None or max_value == None:
                return None
            xlim = (min_value, max_value)
            for j in range(self.screen_rows):
                self.plotter.setXlim(j, i, xlim)
        self.plotter.updateDraw()

    @show_on_error
    def get_entry_value_Ymin(self, event=None):
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                min_value = self._get_corrected_float(self.entry_Ymin[i][j].get())
                max_value = self._get_corrected_float(self.entry_Ymax[i][j].get())
                if min_value == None or max_value == None:
                    return None
                ylim = (min_value, max_value)
                self.plotter.setYlim(i, j, ylim)
        self.plotter.updateDraw()

    @show_on_error
    def get_entry_value_Ymax(self, event=None):
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                min_value = self._get_corrected_float(self.entry_Ymin[i][j].get())
                max_value = self._get_corrected_float(self.entry_Ymax[i][j].get())
                if min_value == None or max_value == None:
                    return None
                ylim = (min_value, max_value)
                self.plotter.setYlim(i, j, ylim)
        self.plotter.updateDraw()

    @show_on_error
    def _init_XYlim_entry_from_plot(self):
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                self.plotter.ax[i][j].callbacks.connect('xlim_changed', self._on_xlim_changed)
                self.plotter.ax[i][j].callbacks.connect('ylim_changed', self._on_ylim_changed)

    @show_on_error
    def _update_ylim_entry_from_plot(self):
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
                ymin, ymax = self.plotter.getYlim(i, j)
                min_value = self._get_corrected_float(self.entry_Ymin[i][j].get())
                max_value = self._get_corrected_float(self.entry_Ymax[i][j].get())

                if min_value != ymin:
                    self.entry_Ymin[i][j].delete(0,tk.END)
                    self.entry_Ymin[i][j].insert(tk.END, f'{ymin}')

                if max_value != ymax:
                    self.entry_Ymax[i][j].delete(0,tk.END)
                    self.entry_Ymax[i][j].insert(tk.END, f'{ymax}')

    @show_on_error
    def _update_xlim_entry_from_plot(self):

        if self._xlim_change_row == None:
            row_changed = list(range(self.screen_rows))
            row_remove = None
            flag_found = False
            for i in range(self.screen_rows):
                for j in range(self.screen_columns):
                    xmin, xmax = self.plotter.getXlim(i, j)
                    min_value = self._get_corrected_float(self.entry_Xmin[j].get())
                    max_value = self._get_corrected_float(self.entry_Xmax[j].get())

                    if min_value != xmin or max_value != xmax:
                        self._xlim = (xmin, xmax)
                        self._xlim_change_col = j
                        row_remove = i

                        self.entry_Xmin[j].delete(0,tk.END)
                        self.entry_Xmax[j].delete(0,tk.END)
                        self.entry_Xmin[j].insert(tk.END, f'{xmin}')
                        self.entry_Xmax[j].insert(tk.END, f'{xmax}')

                        if row_remove != None:
                            row_changed.remove(row_remove)

                        self._xlim_change_row = row_changed

                        flag_found = True
                        break

                if flag_found:
                    break


        if self._xlim_change_row != None:
            for i in self._xlim_change_row[:]:  # for loop for the list copy of _xlim_change_row using slice
                self._xlim_change_row.remove(i)
                col = self._xlim_change_col
                xlim = self._xlim

                self.plotter.setXlim(i,self._xlim_change_col,xlim)

                if not self._xlim_change_row:
                    self._xlim_change_row = None
                    self._xlim_change_col = None
                    self._xlim = None
                    break

    @show_on_error
    def _on_xlim_changed(self, a):
        self.after(0, self._update_xlim_entry_from_plot)
#        self._update_xlim_entry_from_plot()

    @show_on_error
    def _on_ylim_changed(self, a):
        self.after(0, self._update_ylim_entry_from_plot)


#    @show_on_error
#    def update_XYlim_all(self, xlim, ylim):
#        for i in range(self.screen_rows):
#            for j in range(self.screen_columns):
#                self.plotter.setXlim(i, j, xlim)
#                self.plotter.setYlim(i, j, ylim)
#        self.plotter.updateDraw()

#    @show_on_error
#    def update_offset_all(self, f, val):
#        # if check button is true, all offset updated
#        if self.var_check_syncOffset.get() == True:
#            for i, df_info in enumerate(self.plotter.dataframes):
#                f = df_info["file"]
#                # update the plotter offset
#                self.plotter.update_offset(f, val)
#                # update the tkinter offset
#                self.slider_offset[i].set(val)
#
#        else:
#            self.plotter.update_offset(f, val)


    @show_on_error
    def _check_Legend(self):
        for i in range(self.screen_rows):
            for j in range(self.screen_columns):
#                print(f"processed_data_matrix[{i}][{j}] id =", id(self.plotter.processed_data_matrix[i][j]))
                k=0
                for filename in self.plotter.getFilenames(i,j):
                    for label in self.plotter.getLabels(i,j,filename).values():
                        bool_check= self.var_check_Legend[i][j][k].get()
                        if bool_check != self.plotter.getVisibility(i,j,filename,label):
                            self.plotter.setVisibility(i,j,filename,label,bool_check)

#                        print(f'{i},{j}: label={label}')
#                        print(f'visible check: {self.var_check_Legend[i][j][k].get()}')
#                        print(f'visible plotter: {self.plotter.getVisibility(i,j,filename,label)}')
                        k+=1


    @show_on_error
    def _is_valid_float(self, value: str) -> bool:
        if value == "":
            return True  # 削除中など空は許容

        # 入力途中を許容するパターン
        # 例: "-", "+", ".", "-.", "1e", "1e-", "1e+", など
        partial_patterns = [
            r"^[+-]?$",                   # +, -
            r"^[+-]?\.$",                 # . or -. or +.
            r"^[+-]?\d+\.$",              # 1. or -1.
            r"^[+-]?\d*\.?\d+[eE]?$",     # 1e or 1.2e
            r"^[+-]?\d*\.?\d+[eE][+-]?$", # 1e- or 1.2e
            r"^[+-]?\d*\.?\d+[eE]\d*$",   # 0.2e or 1e3 or 1.23e+5
            r"^[+-]?\d*\.?\d+[eE]\d+$",   # e3 (eの後に数字が続く)+
            r"^\.$",                      # Only .
            r"^[+-]?\.\d+[eE]\d+$",       # .3e3 のような形式
            r"^[+-]?\d*\.\d+[eE]\d+$"     # -.e4 のような形式"
        ]
        for pattern in partial_patterns:
            if re.fullmatch(pattern, value):
                return True

        # 不完全入力を補って float() に通す
        s = value
        if s.endswith("."):
            s += "0"
        if s.startswith("."):
            s = "0"+s
        elif re.search(r"[eE]$", s):
            s += "0"
        elif re.search(r"[eE][+-]$", s):
            s += "0"

        try:
            float(s)
            return True
        except ValueError:
            return False

    def _get_corrected_float(self, s):
        # The insufficient input is ignored and returned as None for no action.
#        # 空白や不完全な記号のみは float にならないので None 扱い
#        if s.strip() in {"", "+", "-", ".", "+.", "-.", "e", "+e", "-e"}:
#            return None

        # 補完ルール適用
#        if s.endswith("."):
#            s += "0"
#        if s.startswith("."):
#            s = "0"+s
#        elif s.startswith("e"):
#            s = "0"+s
#        elif re.search(r"[eE]$", s):
#            s += "0"
#        elif re.search(r"[eE][+-]$", s):
#            s += "0"

        try:
            return float(s)
        except ValueError:
            return None

#        # 空文字は入力中とみなして許容
#        if s == "":
#            return True
#
#        # 入力途中として有効なパターン（1e-、-. などを含む）
#        partial_float_pattern = r"""^[+-]?(
#            ( (\d+(\.\d*)?) | (\.\d+) ) ([eE][+-]?\d*)?     # 完成に近い形式
#            | (\d+)?[eE][+-]?\d*                            # 途中の指数形式（例: 1e-, 2e）
#            | [eE]                                          # e の単体
#            | (\d*)                                         # 数値途中
#            | (\d+)?\.?                                     # 小数途中
#        )?$"""
#
#        return re.fullmatch(partial_float_pattern, s, re.VERBOSE) is not None


    @show_on_error
    def _init_matrix(self, var, row=None, col=None, dep=None):
        if row==None and col==None and dep==None:
            return False
        elif row==None:
            if col==None:
                var = [None for _ in range(dep)]
            elif dep==None:
                var = [None for _ in range(col)]
            else:
                var = [[None for _ in range(dep)] for _ in range(col)]

        elif col==None:
            if dep==None:
                var = [None for _ in range(row)]
            else:
                var = [[None for _ in range(dep)] for _ in range(row)]
        elif dep==None:
            var = [[None for _ in range(col)] for _ in range(row)]
        else:
            var = [[[None for _ in range(dep)] for _ in range(col)] for _ in range(row)]
        
        return var


#    @show_on_error
#    def _wheel_to_opts_canvas_smart(self, event):
#        canvas = getattr(self.frameOpts, "canvas", None)
#        if not canvas:
#            return "break"
#
#        # Shift で“横スクロール意図”をヒント（TkのShiftMaskは 0x0001）
#        is_horizontal_hint = bool(getattr(event, "state", 0) & 0x0001)
#
#        # ステップ（Windows/mac: event.delta / Linux(X11): Button-4/5）
#        if getattr(event, "delta", 0):
#            step = -1 if event.delta > 0 else 1
#        else:
#            num = getattr(event, "num", 0)
#            step = -1 if num == 4 else 1  # 4=up, 5=down
#
#        # 実際に動いたかを事後判定してフォールバック
#        def try_scroll(axis):
#            try:
#                before = canvas.xview() if axis == "x" else canvas.yview()
#                if axis == "x":
#                    canvas.xview_scroll(step, "units")
#                    after = canvas.xview()
#                else:
#                    canvas.yview_scroll(step, "units")
#                    after = canvas.yview()
#                return before != after
#            except Exception:
#                return False
#
#        if is_horizontal_hint:
#            if not try_scroll("x"):
#                try_scroll("y")
#        else:
#            if not try_scroll("y"):
#                try_scroll("x")
#
#        return "break"
#
#    @show_on_error
#    def _bind_combobox_wheel_smart(self, cb):
#        ws = self.tk.call('tk', 'windowingsystem')  # 'win32' / 'aqua' / 'x11'
#        seqs = ["<MouseWheel>", "<Shift-MouseWheel>"]  # Windows/mac 共通
#        if ws == "x11":
#            # Linuxはホイールが Button-4/5 になる（横は Shift 併用で扱う）
#            seqs += ["<Button-4>", "<Button-5>", "<Shift-Button-4>", "<Shift-Button-5>"]
#        for s in seqs:
#            try:
#                cb.bind(s, self._wheel_to_opts_canvas_smart)
#            except Exception:
#                pass

    @show_on_error
    def _canvas_dims(self, canvas):
        """Canvas 内容/表示の実寸を取得"""
        try:
            canvas.update_idletasks()
        except Exception:
            pass
        bbox = canvas.bbox("all")
        if not bbox:
            return 0, 0, canvas.winfo_width(), canvas.winfo_height()
        x1, y1, x2, y2 = bbox
        return (x2 - x1), (y2 - y1), canvas.winfo_width(), canvas.winfo_height()

    @show_on_error
    def _try_scroll_guarded(self, canvas, axis: str, step: int, px_threshold: int = 6) -> bool:
        """axis('x'/'y') に 1 step スクロール。実際の移動pxが閾値未満なら元に戻して False。"""
        cw, ch, vw, vh = self._canvas_dims(canvas)
        if axis == "x":
            before = canvas.xview()
            canvas.xview_scroll(step, "units")
            after  = canvas.xview()
            moved_px = abs((after[0] - before[0]) * max(1, cw))
            if moved_px < px_threshold:
                canvas.xview_moveto(before[0])
                return False
            return True
        else:
            before = canvas.yview()
            canvas.yview_scroll(step, "units")
            after  = canvas.yview()
            moved_px = abs((after[0] - before[0]) * max(1, ch))
            if moved_px < px_threshold:
                canvas.yview_moveto(before[0])
                return False
            return True

    @show_on_error
    def _wheel_to_opts_canvas_strict(self, event):
        """
        Combobox上のホイールを、縦は縦・横(=Shift併用)は横にだけ送る。
        その方向に親がスクロールできなければ何もしない（フォールバックしない）。
        """
        canvas = getattr(self.frameOpts, "canvas", None)
        if not canvas:
            return "break"

        # 横意図の判定：Shift 押下（Tk ShiftMask=0x0001）
        is_horizontal = bool(getattr(event, "state", 0) & 0x0001)

        # ステップ（Win/mac: delta、X11: Button-4/5）
        if getattr(event, "delta", 0):
            step = -1 if event.delta > 0 else 1
        else:
            step = -1 if getattr(event, "num", 0) == 4 else 1  # 4=up, 5=down

        # 実際に動けるかピクセルでガード（微小移動は元に戻す）
        def dims():
            try: canvas.update_idletasks()
            except Exception: pass
            bbox = canvas.bbox("all")
            if not bbox:
                return 0, 0, canvas.winfo_width(), canvas.winfo_height()
            x1,y1,x2,y2 = bbox
            return (x2-x1), (y2-y1), canvas.winfo_width(), canvas.winfo_height()

        def try_scroll(axis, step, px_threshold=6):
            cw,ch,vw,vh = dims()
            if axis == "x":
                b = canvas.xview(); canvas.xview_scroll(step, "units"); a = canvas.xview()
                moved = abs((a[0]-b[0]) * max(1, cw))
                if moved < px_threshold: canvas.xview_moveto(b[0]); return False
                return True
            else:
                b = canvas.yview(); canvas.yview_scroll(step, "units"); a = canvas.yview()
                moved = abs((a[0]-b[0]) * max(1, ch))
                if moved < px_threshold: canvas.yview_moveto(b[0]); return False
                return True

        if is_horizontal:
            # 横だけ試す（動けなければ何もしない）
            try_scroll("x", step)
        else:
            # 縦だけ試す（動けなければ何もしない）
            try_scroll("y", step)

        return "break"

    @show_on_error
    def _bind_combobox_wheel_smart(self, cb):
        """プラットフォーム安全なイベントだけバインド（x11は Button-4/5 も）"""
        ws = self.tk.call('tk', 'windowingsystem')  # 'win32' / 'aqua' / 'x11'
        seqs = ["<MouseWheel>", "<Shift-MouseWheel>"]
        if ws == "x11":
            seqs += ["<Button-4>", "<Button-5>", "<Shift-Button-4>", "<Shift-Button-5>"]
        for s in seqs:
            cb.bind(s, self._wheel_to_opts_canvas_strict)

    @show_on_error
    def _file_open(self):
        pass

    @show_on_error
    def _file_save(self):
        pass

    @show_on_error
    def _file_saveas(self):
        pass

    @show_on_error
    def _change_screen(self):
        pass

    @show_on_error
    def _reset_plot(self):
        pass

    @show_on_error
    def _load_settings(self):
        pass

    @show_on_error
    def _create_menu(self):
        self.menu = tk.Menu(self, bg='#EEEEEE', activebackground='#DDDDDD')
        self.menu_file = tk.Menu(self.menu, tearoff=False)
        self.menu_edit = tk.Menu(self.menu, tearoff=False)
        self.menu_edit_screen = tk.Menu(self.menu_edit, tearoff=False)
        self.menu_edit_loadsettings= tk.Menu(self.menu_edit, tearoff=False)

        # add the menubar to the window
        self.config(menu=self.menu)

        # add elements to the menubar
        self.menu.add_cascade(label='File', menu=self.menu_file)
        self.menu.add_cascade(label='Edit', menu=self.menu_edit)

        # add elements to the file
        self.menu_file.add_command(label='Open', command=self._file_open)
        self.menu_file.add_command(label='Save', command=self._file_save)
        self.menu_file.add_command(label='Save as', command=self._file_saveas)

        # add elements to the edit 
        self.menu_edit.add_command(label='Screen', command=self._change_screen)
        self.menu_edit.add_command(label='Reset', command=self._reset_plot)
        self.menu_edit.add_cascade(label='Load settings', menu=self.menu_edit_loadsettings)

        # add elements to the screen
        self.menu_edit_loadsettings.add_command(label='Latest', command=self._load_settings)

#    @show_on_error
#    def syncFilter(self):
#        if self.var_check_syncFilter.get():
#            self.var_check_syncOffset= False
#        else:
#            self.var_check_syncOffset= False
#
#    @show_on_error
#    def syncOffset(self):
#        if self.check_syncOffset.get():
#            self.flag_syncOffset = 1
#        else:
#            self.flag_syncOffset = 0
#
    @show_on_error
    def setFrames(self):
        ### get row and col ###
        row, col = self.plotter.getScreenRowCol()
        self.screen_rows = row
        self.screen_columns = col

        # init functions here
        self._init_combo_filter()

        ### Layer declaration ###
        ### layer 0 ###
        self.pane = tk.PanedWindow(self, orient=tk.HORIZONTAL)#'horizontal')
        self.pane_left = tk.PanedWindow(self.pane)
        self.pane_right = tk.PanedWindow(self.pane)

        ### layer 0 ###
        self.frameLeft = tk.Frame(self.pane_left)#, width=50, height=50)
        self.frameRight = tk.Frame(self.pane_right)#, width=50, height=50)

        ### layer 1 ###
        self.framePlot = tk.Frame(self.frameRight)#, width=50, height=50)
        self.frameOpts = ScrollableFrame(self.frameLeft, ht=0)
        self.frameBot = tk.Frame(self.frameLeft)#, width=50, height=50)
        self.frameXaxis = tk.Frame(self.frameRight)#, width=50, height=50)

        ### layer 2 ###
#        for i in numPlot:
#            self.frameL2[i] = tk.Frame(self)
        print(f'row, col: {self.plotter.getScreenRowCol()}')
        self.frameOpt = self._init_matrix(self.frameOpt, row=row, col=col)
        for i in range(row):
            for j in range(col):
                self.frameOpt[i][j] = ScrollableFrame(self.frameOpts.scrollable_frame, hbg='#BBBBBB', ht=2)
#                self.frameOpt[i][j].update_idletasks()
#                self.frameOpt[i][j].pack_propagate(True)
#                self.frameOpt[i][j] = tk.Frame(self.frameOpts.scrollable_frame, bg='white', highlightbackground='#BBBBBB', highlightthickness=10)

        ### layer 3 ###
        self.plotter._initXYlim()   # init here to get the actual value (maybe this must be replaced by update functino)
        for j in range(col):
            self.label_Xmin[j] = tk.Label(self.frameXaxis, text='  x min: ')
            self.label_Xmax[j] = tk.Label(self.frameXaxis, text='  x max: ')
            self.entry_Xmin[j] = tk.Entry(self.frameXaxis, validate='key', validatecommand=self.vcmd)
            self.entry_Xmax[j] = tk.Entry(self.frameXaxis, validate='key', validatecommand=self.vcmd)
            self.entry_Xmin[j].insert(tk.END, f'{self.plotter.default_xlim[0][j][0]}')
            self.entry_Xmax[j].insert(tk.END, f'{self.plotter.default_xlim[0][j][1]}')

            # bind the key
            self.entry_Xmin[j].bind("<Return>", self.get_entry_value_Xmin)
            self.entry_Xmin[j].bind("<FocusOut>", self.get_entry_value_Xmin)
            self.entry_Xmax[j].bind("<Return>", self.get_entry_value_Xmax)
            self.entry_Xmax[j].bind("<FocusOut>", self.get_entry_value_Xmax)


        self.frameYlim = self._init_matrix(self.frameYlim, row=row, col=col)
        self.group = self._init_matrix(self.group, row=row, col=col)
        self.frameXOffset = self._init_matrix(self.frameXOffset, row=row, col=col)
        self.frameYOffset = self._init_matrix(self.frameXOffset, row=row, col=col)
        self.frameFilter = self._init_matrix(self.frameFilter, row=row, col=col)
        self.frameCutoff = self._init_matrix(self.frameCutoff, row=row, col=col)
        for i in range(row):
            for j in range(col):
                label = []
                for filename in self.plotter.getFilenames(i,j):
                    label.extend(list(self.plotter.getLabels(i,j,filename).values()))

                self.group[i][j] = DragSelectCheckGroup(self.frameOpt[i][j], label, default=True, columns=1, pad=1, command=self._check_Legend, title='Legend')
                self.frameYlim[i][j] = tk.Frame(self.frameOpt[i][j])
#                self.frameLegend[i][j] = tk.Frame(self.frameOpt[i][j])
                self.frameXOffset[i][j] = tk.Frame(self.frameOpt[i][j])
                self.frameYOffset[i][j] = tk.Frame(self.frameOpt[i][j])
                self.frameFilter[i][j] = tk.Frame(self.frameOpt[i][j])
                self.frameCutoff[i][j] = tk.Frame(self.frameOpt[i][j])


        self.label_Screen= self._init_matrix(self.label_Screen, row=row, col=col)
        self.label_Ymax= self._init_matrix(self.label_Ymax, row=row, col=col)
        self.label_Ymin= self._init_matrix(self.label_Ymin, row=row, col=col)
        self.entry_Ymax= self._init_matrix(self.entry_Ymax, row=row, col=col)
        self.entry_Ymin= self._init_matrix(self.entry_Ymin, row=row, col=col)

        for i in range(row):
            for j in range(col):
                self.label_Screen[i][j] = tk.Label(self.frameYlim[i][j], text=f'Screen ({i}, {j})')
                self.label_Ymin[i][j] = tk.Label(self.frameYlim[i][j], text=f'y min')#({i})({j}):')
                self.entry_Ymin[i][j] = tk.Entry(self.frameYlim[i][j], width=self._width_yentry, validate='key', validatecommand=self.vcmd)
                self.label_Ymax[i][j] = tk.Label(self.frameYlim[i][j], text=f'y max')#({i})({j}):')
                self.entry_Ymax[i][j] = tk.Entry(self.frameYlim[i][j], width=self._width_yentry, validate='key', validatecommand=self.vcmd)

                self.entry_Ymin[i][j].insert(tk.END, f'{self.plotter.default_ylim[i][j][0]}')
                self.entry_Ymax[i][j].insert(tk.END, f'{self.plotter.default_ylim[i][j][1]}')
                self.entry_Ymin[i][j].bind("<Return>", self.get_entry_value_Ymin)
                self.entry_Ymin[i][j].bind("<FocusOut>", self.get_entry_value_Ymin)
                self.entry_Ymax[i][j].bind("<Return>", self.get_entry_value_Ymax)
                self.entry_Ymax[i][j].bind("<FocusOut>", self.get_entry_value_Ymax)

        num_filenames = len(self.plotter.getFilenames(0,0))
        num_labels = sum(len(self.plotter.getLabels(0,0,filename)) for filename in self.plotter.getFilenames(0,0))
        
        self.label_Legend = self._init_matrix(self.label_Legend, row=row, col=col)
        self.label_XOffset = self._init_matrix(self.label_XOffset, row=row, col=col)
        self.label_YOffset = self._init_matrix(self.label_YOffset, row=row, col=col)
        self.label_Filter = self._init_matrix(self.label_Filter, row=row, col=col)
        self.label_Cutoff = self._init_matrix(self.label_Cutoff, row=row, col=col)
        self.var_check_Legend = self._init_matrix(self.var_check_Legend, row=row, col=col, dep=num_labels)
#        self.check_Legend = self._init_matrix(self.check_Legend, row=row, col=col, dep=num_labels)
        self.var_entry_XOffset = self._init_matrix(self.var_entry_XOffset, row=row, col=col, dep=num_labels)
        self.var_entry_YOffset = self._init_matrix(self.var_entry_YOffset, row=row, col=col, dep=num_labels)
        self.var_combo_Filter= self._init_matrix(self.var_combo_Filter, row=row, col=col, dep=num_labels)
        self.entry_XOffset = self._init_matrix(self.entry_XOffset, row=row, col=col, dep=num_labels)
        self.entry_YOffset = self._init_matrix(self.entry_YOffset, row=row, col=col, dep=num_labels)
        self.combo_Filter = self._init_matrix(self.combo_Filter, row=row, col=col, dep=num_labels)
        self.entry_Cutoff = self._init_matrix(self.entry_Cutoff, row=row, col=col, dep=num_labels)
        self.var_entry_Cutoff = self._init_matrix(self.var_entry_Cutoff, row=row, col=col, dep=num_labels)
        for i in range(row):
            for j in range(col):
                self.var_check_Legend[i][j] = self.group[i][j].vars

                self.label_XOffset[i][j] = tk.Label(self.frameXOffset[i][j], text='X offset')
                self.label_YOffset[i][j] = tk.Label(self.frameYOffset[i][j], text='Y offset')
                self.label_Filter[i][j] = tk.Label(self.frameFilter[i][j], text='Filter')
                self.label_Cutoff[i][j] = tk.Label(self.frameCutoff[i][j], text='Cutoff')
                k=0
                for filename in self.plotter.getFilenames(i,j):
                    for label in self.plotter.getLabels(i,j,filename).values():
#                        self.var_check_Legend[i][j][k] = tk.BooleanVar(master=self.frameLegend[i][j], value=True)
#                        self.check_Legend[i][j][k] = tk.Checkbutton(self.frameLegend[i][j], text=label, variable=self.var_check_Legend[i][j][k], onvalue=True, offvalue=False, command=self._check_Legend)

                        xoffset = self.plotter.getXOffset(i,j,filename,label)
                        yoffset = self.plotter.getYOffset(i,j,filename,label)
                        self.var_entry_XOffset[i][j][k] = tk.StringVar(master=self.frameXOffset[i][j], value=f'{xoffset}')
                        self.entry_XOffset[i][j][k] = tk.Entry(self.frameXOffset[i][j], width=self._width_xoffsetentry, textvariable=self.var_entry_XOffset[i][j][k], validate='key', validatecommand=self.vcmd)
                        self.entry_XOffset[i][j][k].insert(tk.END, f'{xoffset}')
                        self.entry_XOffset[i][j][k].bind("<Return>", self._update_xoffset)
                        self.entry_XOffset[i][j][k].bind("<FocusOut>", self._update_xoffset)

                        self.var_entry_YOffset[i][j][k] = tk.StringVar(master=self.frameYOffset[i][j], value=f'{yoffset}')
                        self.entry_YOffset[i][j][k] = tk.Entry(self.frameYOffset[i][j], width=self._width_yoffsetentry, textvariable=self.var_entry_YOffset[i][j][k], validate='key', validatecommand=self.vcmd)
                        self.entry_YOffset[i][j][k].insert(tk.END, f'{yoffset}')
                        self.entry_YOffset[i][j][k].bind("<Return>", self._update_yoffset)
                        self.entry_YOffset[i][j][k].bind("<FocusOut>", self._update_yoffset)

                        self.var_combo_Filter[i][j][k] = tk.StringVar(master=self.frameFilter[i][j], value=list(self._combo_filter_types.keys())[0])
                        cb = self.combo_Filter[i][j][k] = ttk.Combobox(self.frameFilter[i][j], state='readonly', width=10, values=list(self._combo_filter_types.keys()), textvariable=self.var_combo_Filter[i][j][k])
                        self._bind_combobox_wheel_smart(cb)
                        cb.bind('<<ComboboxSelected>>', self._combo_filter_changed)


                        self.var_entry_Cutoff[i][j][k] = tk.StringVar(master=self.frameCutoff[i][j], value='0.0')
                        self.entry_Cutoff[i][j][k] = tk.Entry(self.frameCutoff[i][j], width=self._width_cutoffentry, textvariable=self.var_entry_Cutoff[i][j][k], validate='key', validatecommand=self.vcmd)
                        self.entry_Cutoff[i][j][k].insert(tk.END, '0.0')
                        self.entry_Cutoff[i][j][k].bind('<Return>', self._combo_filter_changed)
                        self.entry_Cutoff[i][j][k].bind('<FocusOut>', self._combo_filter_changed)
                        k+=1

        self.button_reset = tk.Button(self.frameBot, width=10, text='test', command=lambda: self.quit_me())
        
        self.var_check_syncFilter = tk.BooleanVar(master=self.frameBot)
        self.var_check_syncXOffset = tk.BooleanVar(master=self.frameBot)
        self.var_check_syncYOffset = tk.BooleanVar(master=self.frameBot)
        self.check_syncXOffset = tk.Checkbutton(self.frameBot, text='Sync x offset', variable=self.var_check_syncXOffset)
        self.check_syncYOffset = tk.Checkbutton(self.frameBot, text='Sync y offset', variable=self.var_check_syncYOffset)
        self.check_syncFilter = tk.Checkbutton(self.frameBot, text='Sync filter', variable=self.var_check_syncFilter)

        ## Place with grid ##
        ## layer 5 ##
        for i in range(row):
            for j in range(col):
                self.label_XOffset[i][j].pack(fill=tk.BOTH, expand=True)
                self.label_YOffset[i][j].pack(fill=tk.BOTH, expand=True)
                self.label_Filter[i][j].pack(fill=tk.BOTH, expand=True)
                self.label_Cutoff[i][j].pack(fill=tk.BOTH, expand=True)
                k=0
                for filename in self.plotter.getFilenames(i,j):
                    for label in self.plotter.getLabels(i,j,filename).values():
#                        self.check_Legend[i][j][k].pack(anchor=tk.W, fill=tk.BOTH, expand=True)
                        self.entry_XOffset[i][j][k].pack(fill=tk.BOTH, expand=True)
                        self.entry_YOffset[i][j][k].pack(fill=tk.BOTH, expand=True)
                        self.combo_Filter[i][j][k].pack(fill=tk.BOTH, expand=True)
                        self.entry_Cutoff[i][j][k].pack(fill=tk.BOTH, expand=True)
                        k+=1

        ## layer 4 ##
        for i in range(row):
            for j in range(col):
                self.label_Screen[i][j].pack(fill=tk.BOTH, expand=True)
                self.label_Ymax[i][j].pack(fill=tk.BOTH, expand=True)
                self.entry_Ymax[i][j].pack(fill=tk.BOTH, expand=True)
                self.label_Ymin[i][j].pack(fill=tk.BOTH, expand=True)
                self.entry_Ymin[i][j].pack(fill=tk.BOTH, expand=True)
#                self.label_Ymax[i][j].grid(row=0, column=0, sticky='nsew') 
#                self.entry_Ymax[i][j].grid(row=1, column=0, sticky='nsew') 
#                self.label_Ymin[i][j].grid(row=2, column=0, sticky='nsew') 
#                self.entry_Ymin[i][j].grid(row=3, column=0, sticky='nsew') 


        ## layer 3 ##
        for i in range(row):
            for j in range(col):
                self.frameYlim[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
#                self.frameLegend[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.group[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.frameXOffset[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.frameYOffset[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.frameFilter[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
                self.frameCutoff[i][j].pack(side=tk.LEFT, expand=True, fill=tk.BOTH)


        for j in range(col):
#            self.label_Xmin[j].pack(side=tk.LEFT, anchor=tk.E, expand=True)
#            self.entry_Xmin[j].pack(side=tk.LEFT, anchor=tk.W, expand=True)
#            self.entry_Xmax[j].pack(side=tk.RIGHT, anchor=tk.W, expand=True)
#            self.label_Xmax[j].pack(side=tk.RIGHT, anchor=tk.E, expand=True)
            self.label_Xmin[j].grid(row=0, column=4*j, sticky='nsew') 
            self.entry_Xmin[j].grid(row=0, column=4*j+1, sticky='nsew') 
            self.label_Xmax[j].grid(row=0, column=4*j+2, sticky='nsew') 
            self.entry_Xmax[j].grid(row=0, column=4*j+3, sticky='nsew') 

        self.button_reset.grid(row=0, column=0, sticky='nsew')
        self.check_syncFilter.grid(row=0, column=1, sticky='nsew')
        self.check_syncXOffset.grid(row=0, column=2, sticky='nsew')
        self.check_syncYOffset.grid(row=0, column=3, sticky='nsew')

        ## layer 2 ##
        for i in range(row):
            for j in range(col):
                self.frameOpt[i][j].grid(row=i, column=j, sticky='nsew')#, padx=10, pady=10)
                self.frameOpt[i][j].rowconfigure(0, weight=1)
                self.frameOpt[i][j].columnconfigure(0, weight=1)
                self.frameOpt[i][j].update_idletasks()
                self.frameOpt[i][j].canvas.config(height=min(self.frameOpt[i][j].scrollable_frame.winfo_reqheight(), 10), width=min(self.frameOpt[i][j].scrollable_frame.winfo_reqwidth(), 10))

        self.canvas = FigureCanvasTkAgg(self.plotter.fig, master=self.framePlot)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        tkagg.NavigationToolbar2Tk(self.canvas, self.framePlot)    # add the navitaion tool of matplotlib on tk canvas.

        ## layer 1 ##
#        self.frameOpts.grid(row=0, column=0, sticky='nsew')
        self.frameOpts.pack(fill=tk.BOTH, expand=True)#, side=tk.TOP)
        self.frameOpts.rowconfigure(0, weight=1)
        self.frameOpts.columnconfigure(0, weight=1)
#        self.frameBot.grid(row=1, column=0, sticky='nsew')
        self.frameBot.pack(side=tk.BOTTOM)#, fill=tk.BOTH, expand=True)#, side=tk.TOP)
#        self.framePlot.grid(row=0, column=1, sticky='nsew')
        self.framePlot.pack(fill=tk.BOTH, expand=True)#, side=tk.TOP)
#        self.frameXaxis.grid(row=1, column=1, sticky='nsew')
        self.frameXaxis.pack(fill=tk.BOTH, expand=False)#, side=tk.BOTTOM)

        ## layer 0 ##
#        self.frameRight.grid(row=0, column=0, sticky='nsew')
#        self.frameLeft.grid(row=0, column=0, sticky='nsew')
        self.frameRight.pack(fill=tk.BOTH, expand=True)#, side=tk.TOP)
        self.frameLeft.pack(fill=tk.BOTH, expand=True)#, side=tk.TOP)

        self.pane_left.add(self.frameLeft, stretch='always')
        self.pane_right.add(self.frameRight, stretch='always')

        self.pane.add(self.pane_left, stretch='always')
        self.pane.add(self.pane_right, stretch='always')
        self.pane.grid(row=0, column=0, sticky='nsew')
#        self.pane.pack(fill=tk.BOTH, expand=True)#, side=tk.TOP)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._create_menu()


class DragSelectCheckGroup(tk.Frame):
    """
    オーバーレイ無し版。
    左ドラッグ＝一括オン、右ドラッグ＝一括オフ。
    小移動（クリック相当）は左＝単体トグル（invokeでcommand発火）、右＝単体オフ。
    ドラッグ中は範囲内のチェックボックスをハイライト表示。
    """
    def __init__(self, master, labels, default=False, columns=4, pad=6,
                 command=None, fire_command_on_batch=True, title=None, **kwargs):
        super().__init__(master, **kwargs)
        self.columns = max(1, int(columns))
        self.pad = int(pad)
        self.user_command = command
        self.fire_command_on_batch = fire_command_on_batch

        # 配置用フレーム
        self.body = tk.Frame(self, bg=self.cget("bg"))
        self.body.pack(fill="both", expand=True)

        # Title
        self.title = {}
        if title != None:
            self.title = tk.Label(self.body, text=f'{str(title)}')
            self.title.grid(row=0, column=0, padx=self.pad, pady=self.pad, sticky="w")

        # Checkbutton群
        self.vars: list[tk.BooleanVar] = []
        self.checks: list[tk.Checkbutton] = []
        self.orig_bg = {}
        for i, text in enumerate(labels):
            var = tk.BooleanVar(master=self.body, value=default)
            chk = tk.Checkbutton(
                self.body, text=text, variable=var,
                onvalue=True, offvalue=False, anchor="w",
                command=self.user_command  # ← 単体クリックでは invoke() で発火させる
            )
            r, c = divmod(i, self.columns)
            if title != None:
                chk.grid(row=r+1, column=c, padx=self.pad, pady=self.pad, sticky="w")
            else:
                chk.grid(row=r, column=c, padx=self.pad, pady=self.pad, sticky="w")

            # 既定動作は止めて、こちらで処理
            chk.bind("<ButtonPress-1>",  self._press_left_from_child)
            chk.bind("<ButtonPress-3>",  self._press_right_from_child)
            chk.bind("<ButtonRelease-1>", self._release_left_from_child)
            chk.bind("<ButtonRelease-3>", self._release_right_from_child)

            self.orig_bg[i] = chk.cget("bg")
            self.vars.append(var)
            self.checks.append(chk)

        self.update_idletasks()

        # ドラッグ状態
        self.dragging = False
        self.button = None          # 1 or 3
        self.start_root = (0, 0)    # 画面座標（クリック開始）
        self.start_body = (0, 0)    # body座標（クリック開始）
        self.drag_threshold = 7     # クリック/ドラッグのしきい値
        self.preview_set: set[int] = set()
        self.preview_color = "#d6ebff"

        # 空き領域での押下にも対応
        self.body.bind("<ButtonPress-1>", self._press_left_from_body)
        self.body.bind("<ButtonPress-3>", self._press_right_from_body)

    # ===== 基本ユーティリティ =====
    def _root_to_body(self, rx, ry):
        bx, by = self.body.winfo_rootx(), self.body.winfo_rooty()
        return rx - bx, ry - by

    def _bbox_in_body(self, w: tk.Widget):
        return (w.winfo_x(), w.winfo_y(),
                w.winfo_x() + w.winfo_width(),
                w.winfo_y() + w.winfo_height())

    def _intersects(self, a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return not (ax2 < bx1 or ax1 > bx2 or ay2 < by1 or ay1 > by2)

    def _items_in_rect_body(self, rect):
        hits = []
        for idx, w in enumerate(self.checks):
            bbox = self._bbox_in_body(w)
            if self._intersects(rect, bbox):
                hits.append(idx)
        return hits

    def _widget_at_root(self, rx, ry):
        return self.winfo_toplevel().winfo_containing(rx, ry)

    def _find_check_ancestor(self, w):
        while w is not None:
            if w in self.checks:
                return w
            w = getattr(w, "master", None)
        return None

    # ===== ハイライト =====
    def _apply_preview(self, new_set: set[int]):
        # remove
        for idx in (self.preview_set - new_set):
            chk = self.checks[idx]
            bg = self.orig_bg[idx]
            try:
                chk.configure(bg=bg, activebackground=bg)
            except tk.TclError:
                pass
        # add
        for idx in (new_set - self.preview_set):
            chk = self.checks[idx]
            try:
                chk.configure(bg=self.preview_color, activebackground=self.preview_color)
            except tk.TclError:
                pass
        self.preview_set = new_set

    def _clear_preview(self):
        self._apply_preview(set())

    # ===== クリック/ドラッグ開始（子/空き領域）=====
    def _press_left_from_child(self, event):  return self._start_drag(1, event.x_root, event.y_root, break_default=True)
    def _press_right_from_child(self, event): return self._start_drag(3, event.x_root, event.y_root, break_default=True)
    def _press_left_from_body(self, event):   return self._start_drag(1, event.x_root, event.y_root, break_default=False)
    def _press_right_from_body(self, event):  return self._start_drag(3, event.x_root, event.y_root, break_default=False)

    # ===== ドラッグ開始/追跡/終了 =====
    def _start_drag(self, button, rx, ry, break_default: bool):
        self.dragging = True
        self.button = button
        self.start_root = (rx, ry)
        self.start_body = self._root_to_body(rx, ry)
        self._clear_preview()
        # ドラッグ系列を確実に受ける
        try:
            self.body.grab_set()
        except tk.TclError:
            pass
        root = self.winfo_toplevel()
        root.bind_all("<Motion>", self._on_motion_global, add="+")
        root.bind_all("<ButtonRelease-1>", self._on_release_global, add="+")
        root.bind_all("<ButtonRelease-3>", self._on_release_global, add="+")
        return "break" if break_default else None

    def _on_motion_global(self, event):
        if not self.dragging:
            return
        rx, ry = event.x_root, event.y_root
        x0, y0 = self.start_body
        x1, y1 = self._root_to_body(rx, ry)
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        hits = set(self._items_in_rect_body(rect))
        self._apply_preview(hits)

    def _finish_drag_at_root(self, rx, ry, button):
        """Release 時の共通処理"""
        if not self.dragging or self.button != button:
            return

        sx, sy = self.start_root
        moved = (abs(rx - sx) >= self.drag_threshold or abs(ry - sy) >= self.drag_threshold)

        x0, y0 = self.start_body
        x1, y1 = self._root_to_body(rx, ry)
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        indices = self._items_in_rect_body(rect)

        if not moved:
            # 単体クリック
            w = self._widget_at_root(rx, ry)
            chk = self._find_check_ancestor(w)
            if chk is not None:
                if button == 1:
                    # ← これが重要：invoke で command を発火させる
                    chk.invoke()
                else:
                    # 右クリックは単体オフ（必要なら command を手動通知）
                    idx = self.checks.index(chk)
                    if self.vars[idx].get():
                        self.checks[idx].deselect()
                        if self.user_command and self.fire_command_on_batch:
                            try: self.user_command()
                            except TypeError: self.user_command()
        else:
            # ドラッグ範囲に一括適用
            if button == 1:
                # 一括オン
                changed = []
                for idx in indices:
                    if not self.vars[idx].get():
                        self.checks[idx].select()
                        changed.append(idx)
                # .select() では command は呼ばれないので、必要なら手動で通知
                if self.user_command and self.fire_command_on_batch and changed:
                    for _ in changed:
                        try: self.user_command()
                        except TypeError: self.user_command()
            else:
                # 一括オフ
                changed = []
                for idx in indices:
                    if self.vars[idx].get():
                        self.checks[idx].deselect()
                        changed.append(idx)
                if self.user_command and self.fire_command_on_batch and changed:
                    for _ in changed:
                        try: self.user_command()
                        except TypeError: self.user_command()

        self.update_idletasks()
        self._clear_preview()

        # 後片付け
        self.dragging = False
        self.button = None
        try:
            self.body.grab_release()
        except tk.TclError:
            pass
        root = self.winfo_toplevel()
        root.unbind_all("<Motion>")
        root.unbind_all("<ButtonRelease-1>")
        root.unbind_all("<ButtonRelease-3>")

    def _on_release_global(self, event):
        btn = 1 if event.num == 1 else 3
        self._finish_drag_at_root(event.x_root, event.y_root, btn)

    def _release_left_from_child(self, event):
        self._finish_drag_at_root(event.x_root, event.y_root, 1)
        return "break"

    def _release_right_from_child(self, event):
        self._finish_drag_at_root(event.x_root, event.y_root, 3)
        return "break"

    # 便利関数
    def get_states(self):
        return [v.get() for v in self.vars]

    def set_all(self, state: bool):
        if state:
            for idx, v in enumerate(self.vars):
                if not v.get():
                    self.checks[idx].select()
                    if self.user_command and self.fire_command_on_batch:
                        try: self.user_command()
                        except TypeError: self.user_command()
        else:
            for idx, v in enumerate(self.vars):
                if v.get():
                    self.checks[idx].deselect()
                    if self.user_command and self.fire_command_on_batch:
                        try: self.user_command()
                        except TypeError: self.user_command()
        self.update_idletasks()



class tkFrame(tk.Frame):
    @show_on_error
    def __init__(self, parent, controller):
        tk.Frame.__init__(self, parent) # arg of parent is a tk.Frame object whose grid is defined. arg of controller is a tk/Tk object which has frames to be shown.
        self.controller = controller

#        plotter = CSVPlotter(processor.dataframes)
#        plotter.plot()
#        self.fig = plotter.fig

        canvas_width = controller.canvas_width
        canvas_height = controller.canvas_height

        canvas = tk.Canvas(self, width=canvas_width, height=canvas_height)
        canvas.pack()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack()
        
        self.controller.update()
#        self.controller.deiconify()



## the csv plotter raw functions
@show_on_error
def initParser(instance):   ## test check if the argument option specifying the data type
    instance.parser = argparse.ArgumentParser(description='')
    instance.parser.add_argument('-m','--mode', default='gui', required=True, choices=['cui','gui'], help='Mode to run the program (cui: CUI mode,  gui: GUI mode')
    instance.parser.add_argument('-p','--path', help='Path of directory/file to be plotted.')
    instance.parser.add_argument('-t','--thin', default = 1, help='The number of thined data (if thin == 9 then the one out of 10 data is available (9 data are omitted).')
    instance.parser.add_argument('-s','--screen', default = '1x1', help='The number of screens (e.g., 2x1 is two rows and 1 column screens).')

    instance.args = instance.parser.parse_args()


@show_on_error
def main():
    # create instances 
    plotter = CsvPlotter()
    processor = FileProcessor()

    # set the argparse
    initParser(plotter)
    print(plotter.args.mode)

    # conditional branch: CUI or GUI
    if ('c' or 'cui') in plotter.args.mode:
        print('CUI mode')

        # get path of directory/file
        processor.input_text_cui()

        # load csv data
        processor.load_csvs()

        # get the arguments

        # cui plotter
#        plotter = CsvPlotter(processor.dataframes)
        plotter.setDataframe(processor.dataframes)
        plotter.setFigAxes()
        plotter.plot(show=True)

        # save csv
        

    elif ('g' or 'gui') in plotter.args.mode:
        print('gui mode')

        # get the info to open csv files
        gui_init = GUI_start()
        gui_init.setFrame()
        gui_init.show_me()

        # get path of directory/file
        print(f'gui_init.path: {gui_init.path}')
        processor.setPath(gui_init.path)

        # load csv data
        processor.load_csvs()
#        print(processor.dataframes)

        plotter.setFigAxes(gui_init.screen)
        plotter.setProcesseddatamatrix(processor.processed_data)
        plotter.plot()

        gui_main = GUI_plotter()
        gui_main.setCsvPlotter(plotter)#processor.dataframes, gui_init.screen)
        gui_main.setFrames()
        gui_main.show_me()

    # exit main


if __name__ == "__main__":
    print(f"--- CSV Plotter {version_CsvPlotter} ---")
    main()

#    processor = FileProcessor()
#    processor.input_text_cui()
#    processor.load_csvs()
#    gui = GUI_plotter()
#    plotter = CsvPlotter(processor.dataframes)
#    plotter.plot()
#    gui.mainloop()


