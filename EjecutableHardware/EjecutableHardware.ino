#include <WiFi.h>
#include <Wire.h>
#include <LiquidCrystal_PCF8574.h>
#include <SPI.h>
#include <MFRC522.h>
#include <HTTPClient.h>
#include "secrets.h"

// --- Pines RFID ---
#define SS_PIN 5       // SDA/NSS del RC522
#define RST_PIN 25     // RST del RC522
#define SPI_SCK 18
#define SPI_MISO 19
#define SPI_MOSI 23

// --- Pines Relé y LED ---
#define RELAY_PIN 4    // GPIO4 al relé
#define LED_PIN 2      // LED azul integrado ESP32

// --- LCD ---
#define LCD_ADDR 0x27  // Cambiar a 0x3F si el módulo LCD lo usa
LiquidCrystal_PCF8574 lcd(LCD_ADDR);

// --- RFID ---
MFRC522 mfrc522(SS_PIN, RST_PIN);

// --- Métricas ---
unsigned long tiempoLectura = 0;
unsigned long tiempoReconexionWiFi = 0;
unsigned long ultimaDesconexionWiFi = 0;
bool wifiConectadoAnterior = false;

void setup() {
  Serial.begin(115200);
  delay(100);

  // --- Pines ---
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);  // Relé inactivo
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // --- LCD ---
  Wire.begin(22, 21);
  lcd.begin(16, 2);
  lcd.setBacklight(255);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Iniciando...");

  // --- Conectar WiFi ---
  Serial.print("Conectando a WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int intentos = 0;
  while (WiFi.status() != WL_CONNECTED && intentos < 30) {
    delay(500);
    Serial.print(".");
    intentos++;
  }

  lcd.clear();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi conectado");
    Serial.print("IP Local: ");
    Serial.println(WiFi.localIP());
    lcd.setCursor(0, 0);
    lcd.print("WiFi OK");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP().toString());
    digitalWrite(LED_PIN, HIGH);
  } else {
    Serial.println("\nError WiFi");
    lcd.setCursor(0, 0);
    lcd.print("Error WiFi");
    digitalWrite(LED_PIN, LOW);
  }

  delay(1500);

  // --- Inicializar RFID ---
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, SS_PIN);
  mfrc522.PCD_Init();
  delay(50);
  Serial.println("RC522 listo. Acerca tarjeta...");
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Acercar tarjeta");

  // --- Inicializar estado WiFi ---
  wifiConectadoAnterior = (WiFi.status() == WL_CONNECTED);
}

void loop() {
  // --- Detectar reconexión WiFi ---
  bool wifiConectadoActual = (WiFi.status() == WL_CONNECTED);
  if (!wifiConectadoAnterior && wifiConectadoActual) {
    // WiFi se reconectó
    tiempoReconexionWiFi = millis() - ultimaDesconexionWiFi;
    Serial.print("WiFi reconectado en ");
    Serial.print(tiempoReconexionWiFi);
    Serial.println(" ms");
  } else if (wifiConectadoAnterior && !wifiConectadoActual) {
    // WiFi se desconectó
    ultimaDesconexionWiFi = millis();
    Serial.println("WiFi desconectado. Intentando reconectar...");
    WiFi.reconnect();
  }
  wifiConectadoAnterior = wifiConectadoActual;

  // --- Esperar tarjeta ---
  if (!mfrc522.PICC_IsNewCardPresent()) return;
  unsigned long inicioValidacion = millis();
  if (!mfrc522.PICC_ReadCardSerial()) return;

  // --- Leer UID ---
  String uid = "";
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(mfrc522.uid.uidByte[i], HEX);
  }
  uid.toLowerCase();
  
  Serial.print("UID leído (hex): ");
  Serial.println(uid);

  // --- Enviar al servidor ---
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-Token", DEVICE_TOKEN);

    String payload = "{\"uid\":\"" + uid + "\",\"tiempo_reconexion_wifi\":" + String(tiempoReconexionWiFi) + "}";
    int httpResponseCode = http.POST(payload);
    
    long logId = 0;

    if (httpResponseCode > 0) {
      String response = http.getString();
      tiempoLectura = millis() - inicioValidacion;
      tiempoReconexionWiFi = 0;
      logId = extraerLogId(response);
      Serial.print("Tiempo de lectura: ");
      Serial.print(tiempoLectura);
      Serial.println(" ms");
      Serial.println("Respuesta servidor: " + response);

      if (response.indexOf("Acceso autorizado") != -1) {
        Serial.println("ACCESO AUTORIZADO - UID: " + uid);
        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("Acceso Valido");
        lcd.setCursor(0, 1);
        lcd.print("Bienvenido");
        abrirCerradura();
      } else {
        Serial.println("ACCESO DENEGADO - UID: " + uid);
        Serial.println("   Razón: " + response);
        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("Acceso denegado");
        delay(2000);
      }

    } else {
      Serial.print("Error HTTP: ");
      Serial.println(httpResponseCode);
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Error de red");
      delay(2000);
    }

    http.end();
    if (logId > 0) reportarTiempoLectura(logId);
  } else {
    Serial.println("WiFi desconectado");
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Sin WiFi");
    delay(2000);
  }

  // --- Detener lectura ---
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Acercar tarjeta");
  delay(300);
}

long extraerLogId(const String& response) {
  int inicio = response.indexOf("\"log_id\":");
  if (inicio == -1) return 0;
  return response.substring(inicio + 9).toInt();
}

// El tiempo total solo se conoce al recibir la respuesta, por eso se envía aparte
void reportarTiempoLectura(long logId) {
  HTTPClient http;
  http.begin(METRICS_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.POST("{\"log_id\":" + String(logId) + ",\"tiempo_lectura\":" + String(tiempoLectura) + "}");
  http.end();
}

void abrirCerradura() {
  digitalWrite(RELAY_PIN, LOW);
  Serial.println("Cerradura abierta");
  delay(3000);
  digitalWrite(RELAY_PIN, HIGH);
  Serial.println("Cerradura cerrada");
}
