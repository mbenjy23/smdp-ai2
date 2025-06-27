from flask import Flask, request, Response
import threading
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse 

from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import re
import os
from textwrap import wrap

# Clé API OpenAI en dur (remplace par la tienne)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_whatsapp_number = os.environ.get("TWILIO_WHATSAPP_NUMBER")

client_twilio = Client(twilio_sid, twilio_token)

# Initialisation de l'application Flask
app = Flask(__name__)

def summarize_long_transcript(transcript_text):
    from textwrap import wrap

    # Chaque chunk ~9000 caractères ≈ ~2200 tokens
    CHUNK_SIZE = 9000
    chunks = wrap(transcript_text, CHUNK_SIZE)

    partial_summaries = []

    # Résume chaque chunk
    for i, chunk in enumerate(chunks):
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Tu es un assistant qui résume des parties de vidéos YouTube."},
                {"role": "user", "content": f"Voici une portion du transcript :\n\n{chunk}\n\nDonne un résumé synthétique en 5 lignes maximum."}
            ],
            temperature=0.7,
        )
        summary_part = response.choices[0].message.content
        partial_summaries.append(summary_part)

    # Fusionner les résumés partiels
    all_summaries = "\n\n".join(partial_summaries)

    # Résumer les résumés
    final_response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Tu es un assistant qui combine plusieurs résumés de parties de vidéos. Mais dans le résumé final, ne parle pas des différentes parties. Parle comme si c'était une seule vidéo."},
            {"role": "user", "content": f"Voici les résumés partiels :\n\n{all_summaries}\n\nDonne-moi un résumé final en 10 lignes."}
        ],
        temperature=0.7,
    )

    return final_response.choices[0].message.content
def traiter_et_envoyer_resume(incoming_msg, from_number):
    youtube_link_pattern = r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)'
    match = re.search(youtube_link_pattern, incoming_msg)

    if match:
        youtube_url = match.group(1)
        video_id = (
            youtube_url.split("watch?v=")[-1].split("&")[0]
            if "watch?v=" in youtube_url
            else youtube_url.split("youtu.be/")[-1].split("?")[0]
        )

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['fr', 'en'])
            transcript_text = "\n".join([t["text"] for t in transcript])
            summary = summarize_long_transcript(transcript_text)
        except Exception as e:
            summary = f"⚠️ Erreur lors du traitement : {str(e)}"
    else:
        summary = "❌ Merci d’envoyer un lien YouTube valide."

    try:
        client_twilio.messages.create(
            from_=twilio_whatsapp_number,
            to=from_number,
            body=summary
        )
        print("✅ Résumé envoyé sur WhatsApp.")
    except Exception as e:
        print(f"❌ Erreur d’envoi Twilio : {str(e)}")


# Fonction de résumé du transcript
def summarize_transcript(transcript_text):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Tu es un assistant qui résume des vidéos YouTube pour WhatsApp."},
            {"role": "user", "content": f"Voici le transcript :\n\n{transcript_text}\n\nFais un résumé clair en 10 lignes maximum, avec les points clés."}
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content

# Webhook WhatsApp
@app.route("/whatsapp", methods=["POST"])
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    from_number = request.values.get("From", "").strip()

    # 🔹 Répondre tout de suite : message d’attente
    resp = MessagingResponse()
    resp.message("📥 Lien reçu ! \n Votre résumé est en cours...\n Cela peut prendre 1 à 2 minutes ⏳")
    response_xml = Response(str(resp), mimetype="application/xml")

    # 🔹 Lancer le traitement dans un thread séparé
    thread = threading.Thread(target=traiter_et_envoyer_resume, args=(incoming_msg, from_number))
    thread.start()

    return response_xml


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)

