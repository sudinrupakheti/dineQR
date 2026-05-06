from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


def analyze_note_sentiment(text):
    if not text:
        return "neutral"

    analyzer = SentimentIntensityAnalyzer()
    score = analyzer.polarity_scores(text)

    # score['compound'] ranges from -1 (Negative) to 1 (Positive)
    if score["compound"] >= 0.05:
        return "positive"
    elif score["compound"] <= -0.05:
        return "negative"
    else:
        return "neutral"
