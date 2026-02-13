import streamlit as st
import pandas as pd
import zipfile
import os
import tempfile
import io
from datetime import datetime
import shutil
import re

from calculations import (
    check_zip_content,
    detect_encoding,
    safe_read_csv,
    perform_calculations
)

st.set_page_config(layout="wide")

OLD_FORMAT = "old"
NEW_FORMAT = "new"


# =========================
# CSV FORMAT DETECTION
# =========================

def detect_csv_format(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            header = f.readline()
            data = f.readline()
    except Exception:
        return "ambiguous"

    semicolons = header.count(";")
    commas = header.count(",")

    has_decimal_comma = bool(re.search(r"\d+,\d+", data))
    has_decimal_dot = bool(re.search(r"\d+\.\d+", data))

    if semicolons > commas and has_decimal_comma:
        return OLD_FORMAT
    if commas > semicolons and has_decimal_dot:
        return NEW_FORMAT

    return "ambiguous"


def _normalize_encoding(enc: str | None) -> str:
    if not enc or enc.lower() == "ascii":
        return "utf-8-sig"
    return enc


def read_csv_with_detected_format(filepath: str, fmt: str) -> pd.DataFrame:
    encoding = _normalize_encoding(detect_encoding(filepath))

    if fmt == OLD_FORMAT:
        df = safe_read_csv(filepath, encoding, ",")
    else:
        try:
            df = pd.read_csv(
                filepath,
                sep=",",
                decimal=".",
                encoding=encoding,
                engine="python"
            )
        except UnicodeDecodeError:
            df = pd.read_csv(
                filepath,
                sep=",",
                decimal=".",
                encoding="latin1",
                engine="python"
            )

    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    if df.shape[1] == 1:
        raise ValueError("CSV konnte nicht korrekt gelesen werden.")

    return df


def read_excel_file(filepath: str) -> pd.DataFrame:
    df = pd.read_excel(filepath, engine="openpyxl")

    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    return df


# =========================
# INPUT CHECK
# =========================

def check_input_and_set_flag(uploaded_file):
    st.session_state.status_messages = []
    st.session_state.input_checked = False
    st.session_state.extracted_files_info = []
    st.session_state.sample_df = None
    st.session_state.results_df = None
    st.session_state.csv_format = None
    st.session_state.file_type = None

    if not uploaded_file:
        return

    if "current_temp_dir" not in st.session_state or \
       not st.session_state.current_temp_dir or \
       not os.path.exists(st.session_state.current_temp_dir):
        st.session_state.current_temp_dir = tempfile.mkdtemp()

    temp_dir = st.session_state.current_temp_dir
    zip_path = os.path.join(temp_dir, uploaded_file.name)

    with open(zip_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    try:
        extracted_files_info = []
        detected_formats = set()
        file_types = set()

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.infolist():
                if member.is_dir():
                    continue

                lower = member.filename.lower()

                if lower.endswith(".csv"):
                    file_types.add("csv")
                elif lower.endswith(".xlsx"):
                    file_types.add("xlsx")
                else:
                    continue

                base = os.path.basename(member.filename)
                target = os.path.join(temp_dir, base)

                with zip_ref.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                extracted_files_info.append((target, base))

                if lower.endswith(".csv"):
                    detected_formats.add(detect_csv_format(target))

        if not extracted_files_info:
            st.session_state.status_messages.append(
                "Fehler: Keine CSV oder XLSX Dateien im ZIP gefunden."
            )
            return

        if len(file_types) > 1:
            st.session_state.status_messages.append(
                "Fehler: ZIP darf nicht CSV und XLSX gleichzeitig enthalten."
            )
            return

        st.session_state.file_type = list(file_types)[0]

        # ================= CSV PATH =================
        if st.session_state.file_type == "csv":
            if len(detected_formats - {"ambiguous"}) > 1:
                st.session_state.status_messages.append(
                    "Fehler: Unterschiedliche CSV-Formate im ZIP erkannt."
                )
                return

            if detected_formats == {NEW_FORMAT}:
                st.session_state.csv_format = NEW_FORMAT
                st.session_state.status_messages.append(
                    "Hinweis: Neues CSV-Format erkannt (, / .)."
                )
            else:
                st.session_state.csv_format = OLD_FORMAT

            file_info = check_zip_content(
                zip_path,
                [p for p, _ in extracted_files_info]
            )
            st.session_state.status_messages.extend(file_info["messages"])

            if file_info["error"]:
                return

            sample_path, _ = extracted_files_info[0]
            st.session_state.sample_df = read_csv_with_detected_format(
                sample_path,
                st.session_state.csv_format
            )

        # ================= XLSX PATH =================
        else:
            st.session_state.status_messages.append(
                "Excel-Dateien erkannt — CSV-Formaterkennung übersprungen."
            )

            sample_path, _ = extracted_files_info[0]
            st.session_state.sample_df = read_excel_file(sample_path)

        st.session_state.extracted_files_info = extracted_files_info
        st.session_state.input_checked = True

    except Exception as e:
        st.session_state.status_messages.append(f"Unerwarteter Fehler: {e}")


# =========================
# MAIN APP
# =========================

def main():
    st.title("Preisupdate Rechner")

    for key, default in {
        "status_messages": [],
        "input_checked": False,
        "sample_df": None,
        "extracted_files_info": [],
        "avg_cols": [],
        "unique_cols": [],
        "results_df": None,
        "csv_format": None,
        "file_type": None,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    col1, col2 = st.columns([1, 2], gap="large")

    with col1:
        st.markdown("### Eingabe")

        uploaded_file = st.file_uploader(
            "ZIP-Datei hier ablegen oder zum Durchsuchen klicken",
            type="zip"
        )

        st.button(
            "Input prüfen",
            disabled=not uploaded_file,
            use_container_width=True,
            on_click=check_input_and_set_flag,
            args=(uploaded_file,)
        )

        st.markdown("### Status")
        with st.container(border=True):
            for msg in st.session_state.status_messages:
                st.markdown(msg)

    with col2:
        st.markdown("### Ergebnisse")

        if st.session_state.input_checked and st.session_state.sample_df is not None:
            st.subheader("Beispieldaten zur Überprüfung")
            st.dataframe(
                st.session_state.sample_df.head(3),
                hide_index=True,
                use_container_width=True
            )

            st.markdown("---")

            header_list = list(st.session_state.sample_df.columns)

            st.session_state.avg_cols = []
            st.session_state.unique_cols = []

            st.write("Wählen Sie Spalten für Durchschnittsberechnung:")
            with st.expander("Spalten für Durchschnitt auswählen", expanded=True):
                for h in header_list:
                    if st.checkbox(h, key=f"avg_{h}"):
                        st.session_state.avg_cols.append(h)

            st.write("Wählen Sie Spalten für Unique-Werte-Zählung:")
            with st.expander("Spalten für Unique-Werte auswählen", expanded=True):
                for h in header_list:
                    if st.checkbox(h, key=f"uniq_{h}"):
                        st.session_state.unique_cols.append(h)

            if st.button("Berechnen", use_container_width=True):
                progress = st.progress(0, text="Berechne Dateien...")
                results = []

                for i, (path, name) in enumerate(
                    st.session_state.extracted_files_info
                ):
                    if st.session_state.file_type == "csv":
                        df = read_csv_with_detected_format(
                            path,
                            st.session_state.csv_format
                        )
                    else:
                        df = read_excel_file(path)

                    metrics = perform_calculations(
                        df,
                        st.session_state.avg_cols,
                        st.session_state.unique_cols
                    )

                    if metrics:
                        row = {"Dateiname": name}
                        row.update(metrics["averages"])
                        row.update(metrics["uniques"])
                        results.append(row)

                    progress.progress((i + 1) / len(st.session_state.extracted_files_info))

                st.session_state.results_df = pd.DataFrame(results)
                progress.empty()

        if st.session_state.results_df is not None:
            st.dataframe(st.session_state.results_df, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                st.session_state.results_df.to_excel(writer, index=False)

            st.download_button(
                "📥 Download als Excel (.xlsx)",
                output.getvalue(),
                file_name=f"preisupdate_ergebnisse_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )


if __name__ == "__main__":
    main()