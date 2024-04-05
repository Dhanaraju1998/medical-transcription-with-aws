from flask import Flask, request, render_template, redirect, url_for, jsonify
import boto3
import os
import json
import uuid
from gtts import gTTS
import tempfile


app = Flask(__name__)


ACCESS_KEY_ID = 'AKIAQ3EGPF7RCDUDEHUC'
SECRET_ACCESS_KEY = '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'
REGION_NAME = 'us-east-1'
S3_BUCKET_NAME = 'demobucketinput01'


def get_media_format(file_name):
    file_extension = os.path.splitext(file_name)[1].lower()
    media_formats = {'.mp3': 'mp3', '.mp4': 'mp4', '.wav': 'wav'}
    return media_formats.get(file_extension, None)

def upload_file_to_s3(file_path, bucket_name):
    s3 = boto3.client('s3',
                      aws_access_key_id=ACCESS_KEY_ID,
                      aws_secret_access_key=SECRET_ACCESS_KEY,
                      region_name=REGION_NAME)

    try:
        unique_filename = str(uuid.uuid4()) + ".mp3"

        s3.upload_file(file_path, bucket_name, unique_filename)

        print("File uploaded successfully.")
        return unique_filename
    except Exception as e:
        print(f"Error uploading file to S3: {e}")
        return None


@app.route('/save_audio', methods=['POST'])
def save_audio():
    text = request.json['text']
    tts = gTTS(text)
    audio_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    tts.write_to_fp(audio_file)
    audio_file.close()

    uploaded_filename = upload_file_to_s3(audio_file.name, BUCKET_NAME)
    if uploaded_filename:
        return jsonify({'filename': uploaded_filename})
    else:
        return jsonify({'error': 'Failed to upload audio to S3'}), 500



def retrieve_files_from_s3(bucket_name):
    s3 = boto3.client('s3',
                      aws_access_key_id=ACCESS_KEY_ID,
                      aws_secret_access_key=SECRET_ACCESS_KEY,
                      region_name=REGION_NAME)

    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in response:
            files = [obj['Key'] for obj in response['Contents']]
            print("Files in the bucket:")
            for file in files:
                print(file)
            return files
        else:
            print("No files found in the bucket.")
            return []
    except Exception as e:
        print(f"Error retrieving files from S3: {e}")
        return []


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload_file')
def upload_file():
    return render_template('upload_file.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "No file uploaded."

    file = request.files['file']
    if file.filename == '':
        return "No selected file."

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    file.save(temp_file.name)

    uploaded_filename = upload_file_to_s3(temp_file.name, BUCKET_NAME)

    temp_file.close()
    os.unlink(temp_file.name)

    return redirect(url_for('upload_file', success='true'))

@app.route('/files')
def list_files():
    files = retrieve_files_from_s3(BUCKET_NAME)

    transcribed_files = {}
    for file in files:
        transcribed_files[file] = False

    for file in files:
        transcript_file_name = f"{os.path.splitext(file)[0]}.json"
        if transcript_file_name in files:
            transcribed_files[file] = True

    return render_template('files.html', files=files, transcribed_files=transcribed_files, bucket_name=BUCKET_NAME)


def extract_medical_terms(transcript_text):
    comprehend_medical_client = boto3.client('comprehendmedical',
                                             aws_access_key_id=ACCESS_KEY_ID,
                                             aws_secret_access_key=SECRET_ACCESS_KEY,
                                             region_name=REGION_NAME)

    try:
        medical_entities = comprehend_medical_client.detect_entities_v2(Text=transcript_text)

        health_terms = [entity['Text'] for entity in medical_entities['Entities'] if
                        entity['Category'] == 'MEDICAL_CONDITION']
        health_terms = list(set(health_terms))
        print("Medical Terms", health_terms)
        return health_terms
    except Exception as e:
        print(f"Error extracting medical terms: {e}")
        return []


@app.route('/transcribe', methods=['POST'])
def transcribe_file():
    file_name = request.form['file_name']
    media_format = get_media_format(file_name)
    if media_format is None:
        return "Unsupported media format."

    transcribe_client = boto3.client('transcribe',
                                     aws_access_key_id=ACCESS_KEY_ID,
                                     aws_secret_access_key=SECRET_ACCESS_KEY,
                                     region_name=REGION_NAME)

    job_name = f'transcription_job_{str(uuid.uuid4())}'

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={'MediaFileUri': f's3://{BUCKET_NAME}/{file_name}'},
        MediaFormat=media_format,
        LanguageCode='en-US',
        OutputBucketName=BUCKET_NAME
    )

    while True:
        job = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        if job['TranscriptionJob']['TranscriptionJobStatus'] in ['COMPLETED', 'FAILED']:
            break

    if job['TranscriptionJob']['TranscriptionJobStatus'] == 'COMPLETED':
        transcript_file_uri = job['TranscriptionJob']['Transcript']['TranscriptFileUri']

        try:
            s3 = boto3.client('s3',
                              aws_access_key_id=ACCESS_KEY_ID,
                              aws_secret_access_key=SECRET_ACCESS_KEY,
                              region_name=REGION_NAME)

            response = s3.get_object(Bucket=BUCKET_NAME, Key=os.path.basename(transcript_file_uri))
            transcript_content = response['Body'].read().decode('utf-8')

            transcript_json = json.loads(transcript_content)
            transcript_text = transcript_json['results']['transcripts'][0]['transcript']

            print(transcript_text)

            medical_terms = extract_medical_terms(transcript_text)
            medical_terms_str = ', '.join(medical_terms)
            print("Medical Words", medical_terms_str)
            return f"Transcript:\n {transcript_text}\n  \n Medical Terms: \n{medical_terms_str}"


        except Exception as e:
            return f"Error retrieving transcript: {e}"
    else:
        return "Transcription job failed."


if __name__ == '__main__':
    app.run(debug=True)
