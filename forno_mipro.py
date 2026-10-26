import os
import sys
import glob
import json
import csv
import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv
from asyncua import Client, ua

# ==============================================================================
# CARICAMENTO CONFIGURAZIONE DA FILE .ENV
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def resolve_path(env_var_name: str, default_folder: str) -> str:
    """Risolve un percorso: se relativo, lo ancora alla BASE_DIR."""
    val = os.getenv(env_var_name, default_folder)
    return val if os.path.isabs(val) else os.path.join(BASE_DIR, val)

OPC_SERVER_URL = os.getenv("OPC_SERVER_URL", "opc.tcp://192.168.1.50:4840")
NAMESPACE_INDEX = int(os.getenv("NAMESPACE_INDEX", "4"))
MACHINE_NAME = os.getenv("MACHINE_NAME", "macchinaSconosciuta")

FOLDER_LOG = resolve_path("FOLDER_LOG", "log")
FOLDER_IN = resolve_path("FOLDER_IN", "queue_in")
FOLDER_PROCESSED = resolve_path("FOLDER_PROCESSED", "processed_in")
FOLDER_OUT = resolve_path("FOLDER_OUT", "telemetria_out")
FOLDER_COMPLETED = resolve_path("FOLDER_COMPLETED", "commesse_concluse")

# Creazione delle cartelle di lavoro
for folder in [FOLDER_LOG, FOLDER_IN, FOLDER_PROCESSED, FOLDER_OUT, FOLDER_COMPLETED]:
    os.makedirs(folder, exist_ok=True)

# ==============================================================================
# CONFIGURAZIONE LOGGING (DEBUG+, ROTAZIONE 14 GIORNI A MEZZANOTTE)
# ==============================================================================
logger = logging.getLogger("OPC_UA_Sync")
logger.setLevel(logging.DEBUG)

log_filepath = os.path.join(FOLDER_LOG, "opc_sync.log")
file_handler = TimedRotatingFileHandler(
    filename=log_filepath,
    when="midnight",
    interval=1,
    backupCount=14,
    encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# ==============================================================================
# MAPPA DEI TAG OPC-UA
# ==============================================================================
TAG_NODES = {
    # Parametri di ricetta e comandi
    "Flag_In": "ns=4;i=12",
    "Nome Commessa": "ns=4;i=23",
    "Set_Temperatura_Zona_1": "ns=4;i=34",
    "Set_Temperatura_Zona_2": "ns=4;i=45",
    "Set_Temperatura_Zona_3": "ns=4;i=56",
    "Set_Temperatura_Zona_4": "ns=4;i=67",
    "Set_Temperatura_Zona_5": "ns=4;i=78",
    "Set_Temperatura_Zona_6": "ns=4;i=89",
    "Flag_Out": "ns=4;i=100",

    # Consuntivi di fine commessa
    "Ora Inizio": "ns=4;i=111",
    "Ora_Fine": "ns=4;i=122",
    "Tempo Lavorazione": "ns=4;i=133",
    "Kwh_Commessa": "ns=4;i=166",

    # Telemetria periodica
    "Consumo_Kw": "ns=4;i=144",
    "Consumo_Kwh": "ns=4;i=155",
    "Read_Temparatura_Zona_1": "ns=4;i=177",
    "Read_Temparatura_Zona_2": "ns=4;i=188",
    "Read_Temparatura_Zona_3": "ns=4;i=199",
    "Read_Temparatura_Zona_4": "ns=4;i=210",
    "Read_Temparatura_Zona_5": "ns=4;i=221",
    "Read_Temparatura_Zona_6": "ns=4;i=232",
}


def sanitize_value(val):
    """Converte date o valori non nativamente serializzabili in stringhe."""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return val


async def handle_commessa_writing(client: Client):
    """Verifica Flag_In, invia i dati della commessa e imposta Flag_In = True."""
    json_files = glob.glob(os.path.join(FOLDER_IN, "*.json"))
    if not json_files:
        logger.debug("[SCRITTURA] Nessun file JSON presente nella cartella di coda.")
        return

    # 1. Controllo dello stato di Flag_In sul PLC
    try:
        flag_in_node = client.get_node(TAG_NODES["Flag_In"])
        flag_in_status = bool(await flag_in_node.read_value())
        logger.debug(f"[HANDSHAKE] Stato Flag_In su PLC: {flag_in_status}")
    except Exception as e:
        logger.error(f"[HANDSHAKE] Errore verifica Flag_In: {e}")
        return

    if flag_in_status:
        logger.warning(
            "[HANDSHAKE] Flag_In risulta TRUE: la commessa precedente non è ancora "
            "stata accettata dall'operatore. Scrittura rimandata."
        )
        return

    # 2. Scrittura della nuova commessa
    json_files.sort(key=os.path.getmtime)
    target_file = json_files[0]
    filename = os.path.basename(target_file)
    logger.info(f"[SCRITTURA] Elaborazione file: {filename}")

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Scrittura Nome Commessa (String)
        commessa_name = str(data.get("nome_commessa", ""))
        logger.debug(f"[SCRITTURA] Nome Commessa -> '{commessa_name}'")
        node_commessa = client.get_node(TAG_NODES["Nome Commessa"])
        await node_commessa.write_value(ua.DataValue(ua.Variant(commessa_name, ua.VariantType.String)))

        # Scrittura Set Temperature (Float / Real)
        temp_list = data.get("set_temperatura_zone", [])
        for i in range(1, 7):
            tag_name = f"Set_Temperatura_Zona_{i}"
            val = temp_list[i - 1] if len(temp_list) >= i else data.get(f"set_temperatura_zona_{i}")
            if val is not None:
                logger.debug(f"[SCRITTURA] {tag_name} -> {val} °C")
                node_temp = client.get_node(TAG_NODES[tag_name])
                await node_temp.write_value(ua.DataValue(ua.Variant(float(val), ua.VariantType.Float)))

        # Impostazione automatica Flag_In a True
        logger.info("[HANDSHAKE] Ricetta scritta. Impostazione automatica Flag_In = TRUE.")
        await flag_in_node.write_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))

        # Archiviazione del file elaborato
        dest_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        dest_path = os.path.join(FOLDER_PROCESSED, dest_filename)
        os.rename(target_file, dest_path)
        logger.info(f"[SCRITTURA] File archiviato in: {dest_path}")

    except Exception as e:
        logger.exception(f"[SCRITTURA] Errore durante l'elaborazione di {filename}: {e}")
        raise


async def handle_telemetry_and_completion(client: Client):
    """Esegue la lettura dei tag, esporta il CSV di snapshot e gestisce Flag_Out."""
    timestamp_exec = datetime.now()
    telemetry = {"timestamp_rilevamento": timestamp_exec.strftime("%Y-%m-%d %H:%M:%S")}
    raw_values = {}

    logger.debug("[LETTURA] Rilevamento variabili in corso...")
    for tag_name, node_str in TAG_NODES.items():
        try:
            node = client.get_node(node_str)
            val = await node.read_value()
            raw_values[tag_name] = val
            telemetry[tag_name] = sanitize_value(val)
            logger.debug(f"[LETTURA] {tag_name} = {telemetry[tag_name]}")
        except Exception as e:
            logger.warning(f"[LETTURA] Errore sul tag '{tag_name}': {e}")
            telemetry[tag_name] = None
            raw_values[tag_name] = None

    # Esportazione snapshot CSV per ogni esecuzione
    csv_filename = f"{MACHINE_NAME}_{timestamp_exec.strftime('%Y%m%d_%H%M%S')}.csv"
    csv_path = os.path.join(FOLDER_OUT, csv_filename)
    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(telemetry.keys()), delimiter=";")
            writer.writeheader()
            writer.writerow(telemetry)
        logger.info(f"[EXPORT CSV] Telemetria salvata in: {csv_path}")
    except Exception as e:
        logger.error(f"[EXPORT CSV] Impossibile salvare la telemetria: {e}")

    # Gestione fine commessa se Flag_Out è True
    flag_out_active = bool(raw_values.get("Flag_Out"))
    if flag_out_active:
        logger.info("[FINE LAVORAZIONE] Rilevato Flag_Out = TRUE: estrazione dati consuntivi.")

        consuntivo = {
            "Data_Consuntivo": timestamp_exec.strftime("%Y-%m-%d %H:%M:%S"),
            "Nome_Commessa": telemetry.get("Nome Commessa"),
            "Ora_Inizio": telemetry.get("Ora Inizio"),
            "Ora_Fine": telemetry.get("Ora_Fine"),
            "Tempo_Lavorazione_minuti": telemetry.get("Tempo Lavorazione"),
            "Kwh_Commessa": telemetry.get("Kwh_Commessa"),
            "Consumo_Kwh_Totale": telemetry.get("Consumo_Kwh")
        }

        logger.info(
            f"[FINE LAVORAZIONE] Riepilogo commessa '{consuntivo['Nome_Commessa']}': "
            f"Durata={consuntivo['Tempo_Lavorazione_minuti']} min, Energia={consuntivo['Kwh_Commessa']} kWh"
        )

        master_report_path = os.path.join(FOLDER_COMPLETED, "registro_commesse_concluse.csv")
        file_exists = os.path.exists(master_report_path)
        try:
            with open(master_report_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(consuntivo.keys()), delimiter=";")
                if not file_exists:
                    writer.writeheader()
                writer.writerow(consuntivo)
            logger.info(f"[FINE LAVORAZIONE] Dati registrati in: {master_report_path}")
        except Exception as e:
            logger.error(f"[FINE LAVORAZIONE] Errore salvataggio consuntivo: {e}")

        # Reset automatico del Flag_Out sul PLC a False
        try:
            node_flag_out = client.get_node(TAG_NODES["Flag_Out"])
            await node_flag_out.write_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
            logger.info("[HANDSHAKE] Flag_Out resettato a FALSE sul PLC.")
        except Exception as e:
            logger.critical(f"[HANDSHAKE] Impossibile resettare Flag_Out a FALSE: {e}")


async def main():
    logger.info("=== AVVIO CICLO SINCRONIZZAZIONE OPC-UA ===")
    client = Client(url=OPC_SERVER_URL, timeout=8)

    try:
        logger.debug(f"[CONNESSIONE] Connessione a {OPC_SERVER_URL} (NS={NAMESPACE_INDEX})...")
        async with client:
            logger.info("[CONNESSIONE] Connessione stabilita.")

            await handle_commessa_writing(client)
            await handle_telemetry_and_completion(client)

    except Exception as e:
        logger.error(f"[ERRORE GENERALE] Operazione fallita: {e}")
        sys.exit(1)

    logger.info("=== CICLO SINCRONIZZAZIONE CONCLUSO CON SUCCESSO ===")


if __name__ == "__main__":
    asyncio.run(main())