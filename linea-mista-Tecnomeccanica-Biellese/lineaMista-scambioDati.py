import os
import time
import json
import csv
import logging
import shutil
import glob
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv
from opcua import Client, ua

load_dotenv()

OPC_SERVER_URL = os.getenv("OPC_SERVER_URL", "opc.tcp://192.168.0.20:4840")
NAMESPACE_INDEX = int(os.getenv("NAMESPACE_INDEX", 2))

DIR_COMMESSE = os.getenv("DIR_COMMESSE", "./commesse_nuove")
DIR_COMMESSE_ELABORATE = os.getenv("DIR_COMMESSE_ELABORATE", "./commesse_elaborate")
DIR_CSV = os.getenv("DIR_CSV", "./csv_output")

POLLING_INTERVAL_SEC = float(os.getenv("POLLING_INTERVAL_SEC", 1.0))
TELEMETRY_INTERVAL_SEC = float(os.getenv("TELEMETRY_INTERVAL_SEC", 10.0))

os.makedirs(DIR_COMMESSE, exist_ok=True)
os.makedirs(DIR_COMMESSE_ELABORATE, exist_ok=True)
os.makedirs(DIR_CSV, exist_ok=True)

# Generazione nomi file CSV una tantum all'avvio del demone
timestamp_avvio = datetime.now().strftime("%Y%m%d%H%M%S")
CSV_MONITORAGGIO_FILE = os.path.join(DIR_CSV, f"Linea Mista_monitoraggio_{timestamp_avvio}.csv")
CSV_ARCHIVIO_LOTTI_FILE = os.path.join(DIR_CSV, f"Linea Mista_archivioFineLotti_{timestamp_avvio}.csv")

def setup_logger():
    log_dir = "log"
    os.makedirs(log_dir, exist_ok=True)
    log_filepath = os.path.join(log_dir, "industria40.log")

    logger = logging.getLogger("TMB_OPCUA")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = TimedRotatingFileHandler(
        filename=log_filepath,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

logger = setup_logger()

DEVICE_NAME = "PLC-GENERALE"

# Mapping Tag OPC-UA (Gruppi e Variabili)
GRP_SCAMBIO_R = "0_BIT/WORD_SCAMBIO_LINEA>GESTIONALE_(R)"
GRP_SCAMBIO_W = "1_BIT_SCAMBIO_GESTIONALE>LINEA_(W)"
GRP_LOTTO_W   = "2_DATI_LOTTO_DA_GESTIONALE_A_LINEA_(W)"
GRP_LAVORO_R  = "4_VISIONE_DATI_LOTTO_ATTUALI_IN_LAVORO_(R)"
GRP_VEL_R     = "5_VISIONE_VELOCITA'_ATTUALI_(R)"
GRP_ARCHIVIO_R= "6_VISIONE_DATI_LOTTO_DA_ARCHIVIARE_(R)"

RICETTA_TAGS_MAP = [
    ("Numero_Lotto",                    "01_Numero_Lotto",                                                     ua.VariantType.UInt32),
    ("Codice_Lotto",                    "02_Codice_Lotto",                                                     ua.VariantType.String),
    ("Articolo_Lotto",                  "03_Articolo_Lotto",                                                   ua.VariantType.String),
    ("SET_TOTALE_grammi_DOSAGGIO",      "04_SET_TOTALE_grammi_DOSAGGIO_(#####gr)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_RACCOLTA",    "05_SET_VELOCITA'_NASTRO_RACCOLTA_(###.#%)",                           ua.VariantType.Float),
    ("SET_COMPONENTE_CARICATORE_1",     "06_SET_COMPONENTE_CARICATORE_1_(###.#%)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_PUNTE_CAR_1", "07_SET_VELOCITA'_NASTRO_A_PUNTE_SCARICO_CARICATORE_1_(###.#%)",       ua.VariantType.Float),
    ("SET_VELOCITA_CILINDRO_LIM_CAR_1", "08_SET_VELOCITA'_CILINDRO_LIMITATORE_CARICATORE_1_(###.#%)",          ua.VariantType.Float),
    ("SET_VELOCITA_TAVOLA_BASE_CAR_1",  "09_SET_VELOCITA'_AVANZAMENTO_TAVOLA_BASE_CARICATORE_1_(###.#%)",      ua.VariantType.Float),
    ("SET_COMPONENTE_CARICATORE_2",     "10_SET_COMPONENTE_CARICATORE_2_(###.#%)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_PUNTE_CAR_2", "11_SET_VELOCITA'_NASTRO_A_PUNTE_SCARICO_CARICATORE_2_(###.#%)",       ua.VariantType.Float),
    ("SET_VELOCITA_CILINDRO_LIM_CAR_2", "12_SET_VELOCITA'_CILINDRO_LIMITATORE_CARICATORE_2_(###.#%)",          ua.VariantType.Float),
    ("SET_VELOCITA_TAVOLA_BASE_CAR_2",  "13_SET_VELOCITA'_AVANZAMENTO_TAVOLA_BASE_CARICATORE_2_(###.#%)",      ua.VariantType.Float),
    ("SET_COMPONENTE_CARICATORE_3",     "14_SET_COMPONENTE_CARICATORE_3_(###.#%)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_PUNTE_CAR_3", "15_SET_VELOCITA'_NASTRO_A_PUNTE_SCARICO_CARICATORE_3_(###.#%)",       ua.VariantType.Float),
    ("SET_VELOCITA_CILINDRO_LIM_CAR_3", "16_SET_VELOCITA'_CILINDRO_LIMITATORE_CARICATORE_3_(###.#%)",          ua.VariantType.Float),
    ("SET_VELOCITA_TAVOLA_BASE_CAR_3",  "17_SET_VELOCITA'_AVANZAMENTO_TAVOLA_BASE_CARICATORE_3_(###.#%)",      ua.VariantType.Float),
    ("SET_COMPONENTE_CARICATORE_4",     "18_SET_COMPONENTE_CARICATORE_4_(###.#%)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_PUNTE_CAR_4", "19_SET_VELOCITA'_NASTRO_A_PUNTE_SCARICO_CARICATORE_4_(###.#%)",       ua.VariantType.Float),
    ("SET_VELOCITA_CILINDRO_LIM_CAR_4", "20_SET_VELOCITA'_CILINDRO_LIMITATORE_CARICATORE_4_(###.#%)",          ua.VariantType.Float),
    ("SET_VELOCITA_TAVOLA_BASE_CAR_4",  "21_SET_VELOCITA'_AVANZAMENTO_TAVOLA_BASE_CARICATORE_4_(###.#%)",      ua.VariantType.Float),
    ("SET_COMPONENTE_CARICATORE_5",     "22_SET_COMPONENTE_CARICATORE_5_(###.#%)",                             ua.VariantType.Float),
    ("SET_VELOCITA_NASTRO_PUNTE_CAR_5", "23_SET_VELOCITA'_NASTRO_A_PUNTE_SCARICO_CARICATORE_5_(###.#%)",       ua.VariantType.Float),
    ("SET_VELOCITA_CILINDRO_LIM_CAR_5", "24_SET_VELOCITA'_CILINDRO_LIMITATORE_CARICATORE_5_(###.#%)",          ua.VariantType.Float),
    ("SET_VELOCITA_TAVOLA_BASE_CAR_5",  "25_SET_VELOCITA'_AVANZAMENTO_TAVOLA_BASE_CARICATORE_5_(###.#%)",      ua.VariantType.Float),
]

MONITORAGGIO_TAGS = [
    (GRP_SCAMBIO_R, "02_bit_LOTTO_INIZIATO_A_GESTIONALE"),
    (GRP_SCAMBIO_R, "04_bit_LINEA_IN_FUNZIONE_A_GESTIONALE"),
    (GRP_SCAMBIO_R, "05_bit_LINEA_IN_MANUTENZIONE_A_GESTIONALE"),
    (GRP_LAVORO_R,  "01_Numero_Lotto_IN_LAVORO"),
    (GRP_LAVORO_R,  "02_Codice_Lotto_IN_LAVORO"),
    (GRP_LAVORO_R,  "03_Articolo_Lotto_IN_LAVORO"),
    (GRP_LAVORO_R,  "04_VIS_SET_TOTALE_grammi_DOSAGGIO_(#####gr)_(in_lavoro)"),
    (GRP_LAVORO_R,  "05_VIS_SET_VELOCITA'_NASTRO_RACCOLTA_(###.#%)_(in_lavoro)"),
    (GRP_LAVORO_R,  "06_VIS_SET_VELOCITA'_MASTER_LINEA_(in_lavoro)"),
    (GRP_VEL_R,     "01_VIS_VEL_ATTUALE_NASTRO_RACCOLTA_(###.#%)_(misurazione)"),
    (GRP_VEL_R,     "22_VIS_grammi_PESATA_MEDIA_CARICATORE_1_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "23_VIS_grammi_ERRORE_MEDIO_CARICATORE_1_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "24_VIS_grammi_PESATA_MEDIA_CARICATORE_2_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "25_VIS_grammi_ERRORE_MEDIO_CARICATORE_2_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "26_VIS_grammi_PESATA_MEDIA_CARICATORE_3_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "27_VIS_grammi_ERRORE_MEDIO_CARICATORE_3_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "28_VIS_grammi_PESATA_MEDIA_CARICATORE_4_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "29_VIS_grammi_ERRORE_MEDIO_CARICATORE_4_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "30_VIS_grammi_PESATA_MEDIA_CARICATORE_5_(#####gr)_(misurazione)"),
    (GRP_VEL_R,     "31_VIS_grammi_ERRORE_MEDIO_CARICATORE_5_(#####gr)_(misurazione)"),
]

ARCHIVIO_LOTTO_TAGS = [
    (GRP_LAVORO_R,   "01_Numero_Lotto_IN_LAVORO"),
    (GRP_LAVORO_R,   "02_Codice_Lotto_IN_LAVORO"),
    (GRP_LAVORO_R,   "03_Articolo_Lotto_IN_LAVORO"),
    (GRP_ARCHIVIO_R, "01_INIZIO_LOTTO_MINUTI"),
    (GRP_ARCHIVIO_R, "02_INIZIO_LOTTO_ORA"),
    (GRP_ARCHIVIO_R, "03_INIZIO_LOTTO_GIORNO"),
    (GRP_ARCHIVIO_R, "04_INIZIO_LOTTO_MESE"),
    (GRP_ARCHIVIO_R, "05_INIZIO_LOTTO_ANNO"),
    (GRP_ARCHIVIO_R, "06_FINE_LOTTO_MINUTI"),
    (GRP_ARCHIVIO_R, "07_FINE_LOTTO_ORA"),
    (GRP_ARCHIVIO_R, "08_FINE_LOTTO_GIORNO"),
    (GRP_ARCHIVIO_R, "09_FINE_LOTTO_MESE"),
    (GRP_ARCHIVIO_R, "10_FINE_LOTTO_ANNO"),
    (GRP_ARCHIVIO_R, "11_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_TOTALE"),
    (GRP_ARCHIVIO_R, "12_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_CARICATORE_1"),
    (GRP_ARCHIVIO_R, "13_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_CARICATORE_2"),
    (GRP_ARCHIVIO_R, "14_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_CARICATORE_3"),
    (GRP_ARCHIVIO_R, "15_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_CARICATORE_4"),
    (GRP_ARCHIVIO_R, "16_VIS_TOTALIZZAZIONE_PRODUZIONE_Kg_CARICATORE_5"),
]

def get_node(client, group, tag_name):
    node_id_str = f"ns={NAMESPACE_INDEX};s={DEVICE_NAME}.Tags.{group}.{tag_name}"
    # logger.debug(f"Accesso al nodo OPC-UA: {node_id_str}")
    return client.get_node(node_id_str)

def read_tag(client, group, tag_name):
    node = get_node(client, group, tag_name)
    val = node.get_value()
    return val

def write_tag(client, group, tag_name, value, fallback_variant_type=None):
    node = get_node(client, group, tag_name)

    # 1. Rileva il tipo esatto atteso dal server leggendo il Variant corrente
    try:
        current_variant = node.get_data_value().Value
        target_type = current_variant.VariantType if current_variant is not None else fallback_variant_type
    except Exception:
        target_type = fallback_variant_type

    # 2. Conversione del dato Python nel tipo nativo del PLC
    valore_convertito = value
    if target_type == ua.VariantType.Boolean:
        valore_convertito = bool(value)
    elif target_type in (ua.VariantType.Int16, ua.VariantType.Int32):
        valore_convertito = int(value)
    elif target_type in (ua.VariantType.UInt16, ua.VariantType.UInt32):
        valore_convertito = int(value)
    elif target_type in (ua.VariantType.Float, ua.VariantType.Double):
        valore_convertito = float(value)
    elif target_type == ua.VariantType.String:
        valore_convertito = str(value)
    elif target_type == ua.VariantType.Byte:
        valore_convertito = int(value)

    # 3. Creazione del Variant
    variant = ua.Variant(valore_convertito, target_type)

    # 4. Creazione corretta di DataValue con solo il valore (senza timestamp/status)
    dv = ua.DataValue(variant)
    
    # 5. Scrittura del solo attributo Value (Id 13)
    node.set_attribute(ua.AttributeIds.Value, dv)
    
    logger.debug(f"Scrittura Tag [{tag_name}] -> Valore: {valore_convertito} (Tipo: {target_type})")

def append_to_csv(filename, data_dict):
    file_exists = os.path.isfile(filename)
    with open(filename, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(data_dict.keys()), delimiter=";")
        if not file_exists:
            writer.writeheader()
        writer.writerow(data_dict)

def preleva_commessa_piu_vecchia():
    lista_file = glob.glob(os.path.join(DIR_COMMESSE, "*.json"))
    if not lista_file:
        logger.warning(f"Nessun file JSON trovato in '{DIR_COMMESSE}'.")
        return None, None
    
    file_piu_vecchio = min(lista_file, key=os.path.getctime)
    logger.info(f"File commessa selezionato (FIFO): {os.path.basename(file_piu_vecchio)}")
    
    try:
        with open(file_piu_vecchio, mode="r", encoding="utf-8") as f:
            dati = json.load(f)
        
        if isinstance(dati, dict) and "Codice_Lotto" not in dati:
            chiave = list(dati.keys())[0]
            dati = dati[chiave]
            
        return dati, file_piu_vecchio
    except Exception as e:
        logger.error(f"Errore lettura {file_piu_vecchio}: {e}")
        return None, file_piu_vecchio

def valida_commessa(commessa):
    somma_percentuali = (
        float(commessa.get("SET_COMPONENTE_CARICATORE_1", 0.0)) +
        float(commessa.get("SET_COMPONENTE_CARICATORE_2", 0.0)) +
        float(commessa.get("SET_COMPONENTE_CARICATORE_3", 0.0)) +
        float(commessa.get("SET_COMPONENTE_CARICATORE_4", 0.0)) +
        float(commessa.get("SET_COMPONENTE_CARICATORE_5", 0.0))
    )
    totale_grammi = float(commessa.get("SET_TOTALE_grammi_DOSAGGIO", 0.0))

    if abs(somma_percentuali - 100.0) > 0.01:
        logger.error(f"Validazione fallita: somma % = {somma_percentuali}% (deve essere 100%).")
        return False
    if totale_grammi <= 0:
        logger.error(f"Validazione fallita: totale grammi = {totale_grammi} (deve essere > 0).")
        return False
    return True

def gestisci_invio_ricetta(client):
    try:
        commessa, filepath = preleva_commessa_piu_vecchia()
        if not commessa:
            return False

        if not valida_commessa(commessa):
            shutil.move(filepath, os.path.join(DIR_COMMESSE_ELABORATE, os.path.basename(filepath) + ".err"))
            return False

        logger.info("Scrittura parametri ricetta sul PLC in corso...")
        for json_key, tag_name, var_type in RICETTA_TAGS_MAP:
            valore = commessa.get(json_key)
            if valore is None:
                valore = "" if var_type == ua.VariantType.String else 0

            if var_type == ua.VariantType.String:
                valore = str(valore)[:20]
            elif var_type == ua.VariantType.UInt32:
                valore = int(valore)
            elif var_type == ua.VariantType.Float:
                valore = float(valore)

            write_tag(client, GRP_LOTTO_W, tag_name, valore, var_type)

        write_tag(client, GRP_SCAMBIO_W, "01_bit_DATI_LOTTO_RICHIESTI_INVIATI_DA_GESTIONALE", True, ua.VariantType.Boolean)
        logger.info("Ricetta inviata e bit di conferma alzato a ON.")
        
        shutil.move(filepath, os.path.join(DIR_COMMESSE_ELABORATE, os.path.basename(filepath)))
        logger.info(f"File commessa spostato in {DIR_COMMESSE_ELABORATE}.")
        return True

    except Exception as e:
        logger.error(f"Errore durante l'invio della ricetta: {e}", exc_info=True)
        return False

def gestisci_fine_lotto(client):
    try:
        logger.info("Richiesta archiviazione fine lotto rilevata.")
        dati_archivio = {"Timestamp_Archiviazione": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        for grp, tag_name in ARCHIVIO_LOTTO_TAGS:
            dati_archivio[tag_name] = read_tag(client, grp, tag_name)

        append_to_csv(CSV_ARCHIVIO_LOTTI_FILE, dati_archivio)
        logger.info(f"Consuntivi salvati in '{CSV_ARCHIVIO_LOTTI_FILE}'.")

        write_tag(client, GRP_SCAMBIO_W, "02_bit_DATI_FINE_LOTTO_ARCHIVIATI_DA_GESTIONALE", True, ua.VariantType.Boolean)
        return True
    except Exception as e:
        logger.error(f"Errore archiviazione fine lotto: {e}", exc_info=True)
        return False

def registra_telemetria(client):
    try:
        riga_csv = {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        for grp, tag_name in MONITORAGGIO_TAGS:
            riga_csv[tag_name] = read_tag(client, grp, tag_name)
        append_to_csv(CSV_MONITORAGGIO_FILE, riga_csv)
    except Exception as e:
        logger.warning(f"Impossibile registrare la telemetria: {e}")

def main():
    logger.info("Avvio servizio di interconnessione Industria 4.0 - Linea Tecnomeccanica Biellese")
    ultimo_salvataggio_telemetria = 0.0
    inviati_ack_attivo = False
    archiviati_ack_attivo = False

    while True:
        client = Client(OPC_SERVER_URL)
        try:
            logger.info(f"Connessione al server OPC-UA {OPC_SERVER_URL}...")
            client.connect()
            logger.info("Connesso con successo.")

            write_tag(client, GRP_SCAMBIO_W, "01_bit_DATI_LOTTO_RICHIESTI_INVIATI_DA_GESTIONALE", False, ua.VariantType.Boolean)
            write_tag(client, GRP_SCAMBIO_W, "02_bit_DATI_FINE_LOTTO_ARCHIVIATI_DA_GESTIONALE", False, ua.VariantType.Boolean)

            while True:
                inizio_ciclo = time.time()

                req_dati_lotto = read_tag(client, GRP_SCAMBIO_R, "01_bit_RICHIESTA_DATI_LOTTO_A_GESTIONALE")
                req_fine_lotto = read_tag(client, GRP_SCAMBIO_R, "03_bit_FINE_LOTTO_PER_ARCHIVIO_DATI_A_GESTIONALE")

                if req_dati_lotto and not inviati_ack_attivo:
                    if gestisci_invio_ricetta(client):
                        inviati_ack_attivo = True
                elif not req_dati_lotto and inviati_ack_attivo:
                    write_tag(client, GRP_SCAMBIO_W, "01_bit_DATI_LOTTO_RICHIESTI_INVIATI_DA_GESTIONALE", False, ua.VariantType.Boolean)
                    inviati_ack_attivo = False

                if req_fine_lotto and not archiviati_ack_attivo:
                    if gestisci_fine_lotto(client):
                        archiviati_ack_attivo = True
                elif not req_fine_lotto and archiviati_ack_attivo:
                    write_tag(client, GRP_SCAMBIO_W, "02_bit_DATI_FINE_LOTTO_ARCHIVIATI_DA_GESTIONALE", False, ua.VariantType.Boolean)
                    archiviati_ack_attivo = False

                if (inizio_ciclo - ultimo_salvataggio_telemetria) >= TELEMETRY_INTERVAL_SEC:
                    registra_telemetria(client)
                    ultimo_salvataggio_telemetria = inizio_ciclo

                tempo_trascorso = time.time() - inizio_ciclo
                time.sleep(max(0.1, POLLING_INTERVAL_SEC - tempo_trascorso))

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.critical(f"Errore connessione: {e}. Ritentativo tra 5s...")
            time.sleep(5)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

if __name__ == "__main__":
    main()