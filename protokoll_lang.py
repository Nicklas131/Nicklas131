import speech_recognition as sr
import sounddevice as sd
import numpy as np
import wavio
from pathlib import Path
import time
import os
import queue
import threading
import uuid

# ==============================================================================
# --- EINSTELLUNGEN ---
# ==============================================================================
DEVICE_ID = 2
CHUNK_DURATION = 30
AUDIO_TEMP_DIR = "temp_audio"
TRANSCRIPT_FILENAME = "meeting_protokoll_simultan.txt"
# ==============================================================================

audio_queue = queue.Queue()

def transcription_worker(protokoll_pfad, temp_ordner_pfad):
    """
    Dieser "Arbeiter" läuft im Hintergrund (eigener Thread).
    Er holt Audio-Blöcke von der Queue und transkribiert sie.
    """
    r = sr.Recognizer()
    while True:
        try:
            # Warte auf den nächsten Audio-Block (oder das Beenden-Signal)
            # Wenn die Queue leer ist, wird hier eine queue.Empty-Exception ausgelöst.
            audio_data = audio_queue.get(timeout=1)
        except queue.Empty:
            # Die Queue war leer, das ist okay. Einfach weiter warten.
            continue 

        # HIER IST DIE WICHTIGSTE ÄNDERUNG:
        # Wir sind hier nur, wenn audio_queue.get() ERFOLGREICH war.
        # Jetzt nutzen wir try/finally, um sicherzustellen, dass task_done()
        # für DIESES EINE Element immer aufgerufen wird, egal was passiert.
        try:
            if audio_data is None:  # Signal zum Beenden
                break # Die Schleife verlassen

            # Ab hier beginnt die eigentliche Verarbeitung des Audio-Blocks
            samplerate, aufnahme = audio_data
            
            # Erstelle einen einzigartigen Dateinamen für diesen Block
            temp_file_name = f"chunk_{uuid.uuid4()}.wav"
            temp_file_path = temp_ordner_pfad / temp_file_name
            
            # Speichere den Block als WAV-Datei
            wavio.write(str(temp_file_path), aufnahme.astype(np.int16), samplerate, sampwidth=2)
            
            # Transkribiere die temporäre Datei
            with sr.AudioFile(str(temp_file_path)) as source:
                audio_listened = r.record(source)
                try:
                    text = r.recognize_google(audio_listened, language='de-DE')
                    if text.strip():
                        print(f"✍️  Transkribiert: '{text.strip()}'")
                        with open(protokoll_pfad, 'a', encoding='utf-8') as f:
                            f.write(text.strip() + " ")
                            f.flush()
                except (sr.UnknownValueError, sr.RequestError):
                    pass # Fehler ignorieren und mit dem nächsten Block weitermachen
            
            # Temporäre Datei löschen
            os.remove(temp_file_path)

        finally:
            # Signalisiert, dass dieser Block (egal ob Audio oder None) fertig ist.
            # Dies wird jetzt NICHT mehr aufgerufen, wenn die Queue leer war.
            audio_queue.task_done()
# ##############################################################################
# ### ENDE DER ÄNDERUNG ###
# ##############################################################################


# ==============================================================================
# --- HAUPTSKRIPT (unverändert) ---
# ==============================================================================
if __name__ == "__main__":
    script_verzeichnis = Path(__file__).parent
    protokoll_pfad = script_verzeichnis / TRANSCRIPT_FILENAME
    temp_audio_pfad = script_verzeichnis / AUDIO_TEMP_DIR
    
    os.makedirs(temp_audio_pfad, exist_ok=True)
    
    try:
        device_info = sd.query_devices(DEVICE_ID, 'input')
        sample_rate = int(device_info['default_samplerate'])
    except Exception as e:
        print(f"Fehler: Konnte Mikrofon mit ID {DEVICE_ID} nicht finden. {e}")
        exit()

    transcription_thread = threading.Thread(
        target=transcription_worker, 
        args=(protokoll_pfad, temp_audio_pfad), 
        daemon=True
    )
    transcription_thread.start()

    print("Protokoll gestartet. Aufnahme läuft kontinuierlich.")
    print(f"Drücke 'Strg + C' zum Beenden und Speichern.")
    with open(protokoll_pfad, 'w', encoding='utf-8') as f:
        f.write(f"Meeting-Protokoll vom {time.strftime('%d.%m.%Y %H:%M:%S')}\n\n")

    try:
        while True:
            aufnahme = sd.rec(int(CHUNK_DURATION * sample_rate), samplerate=sample_rate, channels=1, dtype=np.int16, device=DEVICE_ID)
            sd.wait()
            audio_queue.put((sample_rate, aufnahme))

    except KeyboardInterrupt:
        print("\n\n⏹️  Beende das Programm...")
        audio_queue.put(None)
        audio_queue.join()
        print("Alle Blöcke transkribiert.")

    finally:
        if os.path.exists(temp_audio_pfad):
            for file in os.listdir(temp_audio_pfad):
                try:
                    os.remove(temp_audio_pfad / file)
                except OSError:
                    pass
            os.rmdir(temp_audio_pfad)
        print(f"Protokoll wurde in '{protokoll_pfad.name}' gespeichert. Programm beendet.")