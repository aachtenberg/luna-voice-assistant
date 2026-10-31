import paho.mqtt.client as mqtt
import tracing
from config import MQTT_BROKER, MQTT_PORT


def mqtt_publish(topic: str, payload: str) -> str:
    """Publish a message to an MQTT topic."""
    try:
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        result = client.publish(topic, payload)
        client.disconnect()

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            return f"Published to {topic}: {payload}"
        else:
            tracing.mark_error("PublishFailed")
            return f"Failed to publish: {result.rc}"
    except Exception as e:
        tracing.mark_error(type(e).__name__)
        return f"MQTT error: {e}"
