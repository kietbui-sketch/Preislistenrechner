# calculations.py
import pandas as pd
import zipfile
import os
import chardet
import streamlit as st

def check_zip_content(zip_path, extracted_files):
    """Checks zip file content. Note: Encoding issues only apply to CSV files, not Excel."""
    messages = []
    files = [os.path.basename(f) for f in extracted_files]
    headers = []
    error = False

    if not files:
        messages.append("Fehler: Keine CSV- oder Excel-Dateien im ZIP-Archiv gefunden.")
        error = True
        return {'messages': messages, 'files': [], 'headers': [], 'error': error}

    file_types = set(f.split('.')[-1].lower() for f in files)
    if len(file_types) > 1:
        messages.append(f"Fehler: Verschiedene Dateitypen gefunden: {', '.join(file_types)}. Alle Dateien müssen vom gleichen Typ sein.")
        error = True
        return {'messages': messages, 'files': [], 'headers': [], 'error': error}
    messages.append(f"Gefundene Dateien: {len(files)}")
    messages.append(f"Dateityp: {file_types.pop()}")

    first_header = None
    for filepath in extracted_files:
        filename = os.path.basename(filepath)
        if filename.lower().endswith('.csv'):
            try:
                # Read only header for CSV
                # Using 'errors=ignore' for reading header line to prevent decode issues at this stage
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    header_line = f.readline().strip()
                    current_header = [col.strip().strip('"') for col in header_line.split(';')]
                    if first_header is None:
                        first_header = current_header
                        headers.append(first_header)
                    elif current_header != first_header:
                        messages.append(f"Fehler: Datei '{filename}' hat unterschiedliche Header.")
                        error = True
                        return {'messages': messages, 'files': [], 'headers': [], 'error': error}
            except Exception as e:
                messages.append(f"Fehler beim Lesen des CSV-Headers von '{filename}': {e}")
                error = True
                return {'messages': messages, 'files': [], 'headers': [], 'error': error}
        elif filename.lower().endswith('.xlsx'):
            try:
                df = pd.read_excel(filepath, nrows=0) # Read only header for Excel
                current_header = [str(h).strip().strip('"') for h in df.columns]
                if first_header is None:
                    first_header = current_header
                    headers.append(first_header)
                elif current_header != first_header:
                    messages.append(f"Fehler: Datei '{filename}' hat unterschiedliche Header.")
                    error = True
                    return {'messages': messages, 'files': [], 'headers': [], 'error': error}
            except Exception as e:
                messages.append(f"Fehler beim Lesen des Excel-Headers von '{filename}': {e}")
                error = True
                return {'messages': messages, 'files': [], 'headers': [], 'error': error}

    if not error and first_header:
        messages.append("Header der Dateien sind identisch.")
    elif not error:
        messages.append("Keine Headerinformationen gefunden.")

    return {'messages': messages, 'files': files, 'headers': headers, 'error': error}

def detect_encoding(file_path):
    """Detects encoding for CSV files only."""
    with open(file_path, 'rb') as f:
        raw_data = f.read(10000)  # Read first 10k bytes to guess encoding
    
    result = chardet.detect(raw_data)
    
    # Heuristic for German characters, prioritizing common German encodings
    # Look for specific byte values common for umlauts and eszett in cp1252/iso-8859-1
    # Example: ü (0xFC), ö (0xF6), ä (0xE4), ß (0xDF)
    german_specific_bytes = [0xFC, 0xF6, 0xE4, 0xDF]
    
    if any(b in raw_data for b in german_specific_bytes):
        # If chardet suggests utf-8 but confidence is low and German chars are present,
        # it might be a misdetection, try cp1252/iso-8859-1.
        if result['encoding'] and 'utf-8' in result['encoding'].lower() and result['confidence'] < 0.9:
            for enc in ['cp1252', 'iso-8859-1']:
                try:
                    raw_data.decode(enc) # Attempt decoding to confirm
                    return enc
                except UnicodeDecodeError:
                    pass # If it fails, try next
        elif result['encoding'].lower() in ['windows-1252', 'iso-8859-1']:
            return result['encoding'] # If detected as these, use them
        
    return result['encoding'] or 'cp1252' # Fallback to detected or cp1252

def safe_read_csv(file_path, encoding, decimal_separator=','):
    """Safely reads CSV files with different encodings and specified decimal separator."""
    encodings_to_try = [
        encoding,  # Try detected encoding first
        'cp1252',
        'iso-8859-1',
        'utf-8',
        'utf-8-sig' # UTF-8 with BOM
    ]
    
    for enc in encodings_to_try:
        try:
            return pd.read_csv(
                file_path, 
                delimiter=';', 
                decimal=decimal_separator, # Use the provided decimal separator
                encoding=enc,
                on_bad_lines='warn',
                low_memory=False # Helps prevent mixed type warnings
            )
        except UnicodeDecodeError:
            continue
        except Exception as e:
            # We don't want to show an error for every failed encoding attempt
            # st.warning(f"Versuch, {file_path} mit Kodierung {enc} zu lesen, fehlgeschlagen: {e}")
            continue
    
    raise ValueError(f"Konnte {file_path} mit keiner der getesteten Kodierungen und Dezimaltrennzeichen '{decimal_separator}' lesen.")

def perform_calculations(df, avg_cols, unique_cols):
    """
    Performs average and unique count calculations for specified lists of columns.
    Returns a dictionary with 'averages' and 'uniques' sub-dictionaries.
    """
    calculated_averages = {}
    calculated_uniques = {}
    
    # Perform average calculations
    for col in avg_cols:
        if col in df.columns:
            try:
                # Convert to numeric, coercing errors to NaN. pd.to_numeric handles both '.' and ','
                # if the column is of 'object' dtype, based on locale or infer_true_values.
                # However, since safe_read_csv now handles `decimal=`, the column should already be numeric.
                numeric_series = pd.to_numeric(df[col], errors='coerce')
                average = numeric_series.dropna().mean()
                calculated_averages[f'{col} Durchschnitt'] = average
            except Exception as e:
                calculated_averages[f'{col} Durchschnitt'] = f"Fehler bei Berechnung"
                st.error(f"Fehler bei Durchschnittsberechnung für Spalte '{col}' in einer Datei: {e}")
        else:
            calculated_averages[f'{col} Durchschnitt'] = "Spalte nicht gefunden"
            # No need for st.warning here, as this is handled by main.py info message

    # Perform unique value calculations
    for col in unique_cols:
        if col in df.columns:
            try:
                unique_count = df[col].dropna().nunique()
                calculated_uniques[f'{col} Unique'] = unique_count
            except Exception as e:
                calculated_uniques[f'{col} Unique'] = f"Fehler bei Zählung"
                st.error(f"Fehler bei Unique-Wert-Zählung für Spalte '{col}' in einer Datei: {e}")
        else:
            calculated_uniques[f'{col} Unique'] = "Spalte nicht gefunden"
            # No need for st.warning here

    # Check if any column was actually selected for calculation
    if not calculated_averages and not calculated_uniques:
        # This condition should ideally be caught by the disabled state of the button or earlier checks
        return None # Indicate no valid metrics calculated
        
    return {'averages': calculated_averages, 'uniques': calculated_uniques}