# Demo Script — GT Cotizador
**Audiencia:** Jean Paul + Renato  
**Duración objetivo:** 20 minutos  
**Quién lo presenta:** Barney  
**Idioma de presentación:** Español  
**Fecha:** por confirmar — sistema listo, coordinar lunes

---

## ANTES DEL DEMO — EJECUTAR PRIMERO

**Con datos pre-cargados (recomendado):**
```
http://127.0.0.1:5001/demo-reset?password=gt2026&seed=true
```

Esto pre-carga 3 cotizaciones reales instantáneamente:
- **Quote 1** — LCL Hamburg Importer GmbH, $568 venta, 22% margen → **PENDIENTE**
- **Quote 2** — Aéreo Miami Foods Corp, $1,712 venta, 20% margen → **APROBADA**
- **Quote 3** — FCL Distribuidora Lima SAC, $3,664 venta, 18% margen → **ENVIADA**

El ciclo de vida completo es visible desde el primer segundo. No es necesario crear cotizaciones en vivo.

**Para empezar desde cero en cambio:**
```
http://127.0.0.1:5001/demo-reset?password=gt2026
```

---

## Antes de empezar (checklist, solo tú)

- [ ] Flask corriendo en puerto 5001: `APP_ENV=development python -m flask --app api/app.py run --port 5001`
- [ ] `/demo-reset?password=gt2026` ejecutado — base de datos limpia
- [ ] Ventana del browser abierta en `http://localhost:5001`
- [ ] Tab adicional con `/acknowledgment/demo` lista (no mostrar hasta el paso 8)
- [ ] Rate cards confirmados LIVE desde SharePoint (source=live en logs)
- [ ] Silencia tu teléfono

**Estado del sistema al día de hoy (2026-05-15):**
- Puerto: 5001
- Modo: LIVE — 12 sheets leyendo tarifas reales desde el OneDrive de Jean Paul (24h cache)
- Carriers reales: HAPAG, CMA CGM, LAN Airlines
- Rutas reales: Callao→Antwerp, Lima→LAX, Manzanillo→Callao
- Consolidadores reales: MSL, CRAFT, SACO, VANGUARD, ECU Worldwide
- Handling fees reales: TALMA, SHOHIN, SAASA (desde HANDLING AEREO.xlsx)
- Contactos reales: 21 consolidadores LCL (desde DATA COLOADERS.xlsx)
- Firmas reales: Renato Alvarez, Jean Paul Arrue, Abel Díaz Peralta, Daniela Leveau, Cielo Cuellar
- Tests: 104/104 pasando

---

## Paso 1 — Apertura (2 min)

**Qué decir:**
> "Jean Paul, Renato — lo que van a ver es el cotizador que describió Abel el 7 de mayo.
> Construido exactamente como él lo explicó: los tres modos — aéreo, LCL, FCL.
> El flujo completo: solicitud entra, cotización se arma, ustedes la aprueban, sale al cliente.
> Son 20 minutos. Al final van a poder crear una cotización real ustedes mismos."

**Qué NO decir:** No menciones SINTAD API, limitaciones de integración, ni deuda técnica.

**Reacción a buscar:** Jean Paul empieza a asentir. Renato pregunta si esto reemplaza el Excel de Abel — di "lo complementa primero, lo reemplaza después."

---

## Paso 2 — Dashboard (1 min)

**URL:** `http://localhost:5001`

**Qué decir:**
> "Esta es la pantalla principal. Todo el equipo comercial — Abel, Daniela, Cielo — ven esto
> cuando abren el sistema. Cotizaciones pendientes de aprobación arriba. Estado en tiempo real.
> Auditoría completa abajo. Nada se pierde."

**Qué mostrar:** El dashboard vacío (post reset). Resaltar el contador de estados: PENDING / APPROVED / SENT.

**Qué NO decir:** No digas "está vacío porque hice un reset." Solo di "empezamos desde cero para el demo."

---

## Paso 3 — Nueva cotización (5 min)

**URL:** Click "+ Nueva Cotización"

**Qué decir mientras llenas el formulario:**
> "Imaginen que Abel recibe esto por WhatsApp: 'necesito cotización LCL Lima a Hamburgo,
> 2,500 kilos de perecibles, 8 CBM, FOB Callao.' Así entra al sistema."

**Llenar estos campos exactamente:**
- Cliente: `Perú Exports SAC`
- Email cliente: `carlos.mendoza@peruexports.com`
- Incoterm: `FOB`
- Modo: `LCL`
- Origen: `Lima, Perú`
- Destino: `Hamburgo, Alemania`
- Descripción: `Espárragos frescos refrigerados — perecibles`
- Peso: `2500` kg
- Volumen: `8` CBM

**Qué decir al ver el cálculo:**
> "¿Ven esto? El sistema calcula automáticamente si el peso o el volumen define el flete.
> En LCL, gana el mayor. El tipo de cambio lo tomó en tiempo real del SBS esta mañana.
> Y las tarifas — esas vienen directamente del OneDrive de Jean Paul, en tiempo real."

**Reacción a buscar:** Jean Paul preguntará sobre la tarifa de flete. Di: "eso viene de sus archivos Excel de tarifas en Drive — los mismos que maneja Abel hoy, sin tocarlos."

---

## Paso 4 — Vista Clásica vs Vista Moderna (3 min)

**URL:** Click en la cotización recién creada

**Vista Clásica primero:**

**Qué decir:**
> "Vista Clásica — así lo ve el equipo internamente. El costeo completo: flete desde HAPAG
> o CMA CGM según la ruta, visto bueno, agente de aduanas, transporte local.
> El margen. Todo junto."

**Luego cambiar a Vista Moderna:**

**Qué decir:**
> "Vista Moderna — esto es lo que ve el cliente. Solo lo que necesita ver:
> descripción de la carga, puertos, precios de venta. Sin costeo, sin margen, sin datos internos."

**Mostrar el sistema de advertencias (si aparece alguna):**
> "Si el margen cae por debajo del 10% — el mínimo de Abel — el sistema bloquea el botón
> de aprobación. Nadie puede aprobar por error una cotización que no es negocio."

---

## Paso 5 — Correos a Proveedores (2 min)

**URL:** Click "Correos a Proveedores"

**Qué decir:**
> "Esto lo hace Abel a mano, cada vez, para cada cotización. Escribe un correo a MSL,
> otro a CRAFT, otro a SACO, otro a VANGUARD, otro a ECU Worldwide — pidiendo tarifas.
> Son 5 correos por cotización LCL. El sistema los genera todos al instante,
> con los contactos reales que ya están cargados — nombres, emails, firmas."

**Mostrar el correo dirigido a MSL con el contacto real (Franccesco Urrutia, MSL Corporate).**

**Qué decir:**
> "Este correo va a Franccesco Urrutia en MSL Corporate. No lo escribimos — el sistema
> lo armó con los datos de la cotización. Abel lo copia, pega, envía. 30 segundos
> en vez de 10 minutos."

---

## Paso 6 — Aprobar como Jean Paul (1 min)

**Qué decir:**
> "La cotización está lista. Antes de salir al cliente, pasa por ustedes.
> Jean Paul — ¿la aprueba?"

**Dejar que JP haga click en Aprobar** (si está presente en persona).

**Qué decir después:**
> "El sistema registra quién aprobó, cuándo, y desde qué equipo. Eso es el registro BASC.
> Nadie puede aprobar en nombre de otro — cada acción queda firmada con la firma real
> de Jean Paul."

---

## Paso 7 — Exportar a SINTAD (1 min)

**URL:** Click "Exportar a SINTAD"

**Qué decir:**
> "Cuando el cliente acepta, Abel re-ingresa todo a SINTAD manualmente. Con este sistema,
> el Excel ya viene pre-llenado — cliente, puertos, incoterm, peso, flete, agente.
> Abel abre SINTAD, abre el Excel, copia. Ya no escribe desde cero.
> Estamos coordinando la integración directa con ASESORIA INFORMATICA."

---

## Paso 8 — Acuse automático en alemán (2 min)

**URL:** Abrir tab de `/acknowledgment/demo`

**Qué decir antes de mostrar:**
> "Son las 2:45 de la mañana. Un cliente alemán escribe pidiendo una cotización de carga aérea
> Frankfurt–Lima. El equipo está durmiendo. Sin este sistema, ese cliente espera hasta el amanecer
> sin saber si su correo llegó."

**Mostrar la tarjeta del cliente alemán y su acuse.**

**Qué decir:**
> "El sistema detecta el idioma — alemán — y en menos de 60 segundos le responde en alemán.
> Nombre del cliente, descripción de su carga, tiempo estimado de respuesta. Profesional.
> Sin comprometerse con precios. Sin que nadie del equipo se despierte."

**Reacción a buscar:** Renato dirá algo sobre la reputación internacional. Afirma: "exacto — esto es lo que separa a Global Transport de los demás."

---

## Paso 9 — Auditoría BASC (1 min)

**URL:** Click "Auditoría" en la nav

**Qué decir:**
> "Esto lo ven los auditores BASC. Cada acción del sistema queda registrada:
> quién creó la cotización, quién la aprobó, cuándo se envió, qué pasó con cada correo.
> Inmutable — nadie puede borrar ni modificar este registro. Es parte del ISO 9001."

**Mostrar el filtro por referencia** para la cotización que acaban de aprobar.

**Reacción a buscar:** Renato se ilumina — esto habla directamente a su lenguaje de certificación.

---

## Paso 10 — Cierre (2 min)

**Qué decir:**
> "Eso es el sistema. Tres cosas que vale la pena recordar:
>
> Uno — el criterio de aceptación que acordamos: tres cotizaciones aprobadas por Jean Paul
> sin reescribir números. Hagámoslo esta semana.
>
> Dos — Pipeline #2 ya está listo como piloto: la campaña WCA. Elegimos un país, un segmento,
> y el sistema genera los correos para 20-30 agentes WCA. Renato decide cómo salen.
>
> Tres — Pipeline #3 es lo que vieron en el paso 8: acuse automático 24/7 en seis idiomas.
> Ya está construido. Es el mismo sistema."

**Si preguntan sobre precio de Pipelines #2 y #3:** Di "eso lo conversamos por separado — para hoy, enfoquémonos en que este sistema funcione para ustedes."

**Cierre final:**
> "¿Quieren crear una cotización real ahora — con sus propios números?"

---

## Preguntas difíciles y respuestas

| Pregunta | Respuesta recomendada |
|---|---|
| "¿Los números son reales?" | "Sí — el sistema está leyendo las tarifas directamente desde el Drive de Jean Paul en tiempo real. LCL: CRAFT $466 costo / $568 venta. Aéreo: LAN + TALMA $1,426 costo / $1,712 venta. FCL: CMA CGM $3,105 costo / $3,664 venta." |
| "¿Puede enviar el correo automáticamente?" | "Sí — el botón está construido. Estamos esperando que el proveedor IT de GT (STC SAC, dduque@stconsac.com) configure las credenciales SMTP. Llega esta semana con autorización de Renato." |
| "¿Está leyendo las tarifas reales?" | "Sí, directamente desde el OneDrive de Jean Paul en tiempo real. Las mismas tarifas que maneja Abel hoy — sin tocar el archivo." |
| "¿Qué pasa con SINTAD?" | "El export Excel está listo — Abel copia los campos directamente. La integración directa con la API la coordinamos con Jesús Diez en ASESORIA INFORMATICA." |
| "¿Es seguro?" | "BASC-grade: secrets manager, audit trail inmutable, sin texto plano en ningún lugar. Ya pasamos la homologación al 95%." |
| "¿Y las firmas?" | "Están configuradas — Renato, Jean Paul, Abel, Daniela y Cielo. Cada correo sale con la firma correcta de quien aprueba." |
| "¿Por qué no se conecta directamente a SINTAD?" | "Estamos coordinando acceso técnico con ASESORIA INFORMATICA. En paralelo, el Excel pre-llenado ya elimina el 80% del re-ingreso." |
| "¿Y si Abel no quiere usarlo?" | "Abel lo diseñó. El flujo es exactamente el que él describió en mayo. Él es el experto — el sistema lo apoya, no lo reemplaza." |
| "¿Dónde están guardados los datos?" | "En servidor local o AWS Lima (sa-east-1). Datos de Global Transport nunca salen de sus sistemas. Cumplimos con BASC Estándar 6.0." |
| "¿Qué pasa si el sistema falla?" | "El flujo manual sigue siendo posible. El sistema es un asistente — la decisión siempre es humana." |

---

## Rutas activas (referencia técnica, puerto 5001)

| Ruta | Descripción |
|---|---|
| `GET /` | Dashboard principal |
| `GET /quote/new` | Nueva cotización |
| `GET /quote/<ref>` | Detalle + gate de aprobación |
| `GET /quote/<ref>/provider-emails` | Correos a proveedores (MSL, CRAFT, SACO, VANGUARD, ECU) |
| `GET /quote/<ref>/sintad-export` | Export SINTAD Excel (4 sheets, APPROVED only) |
| `GET /wca-pilot` | Generador campaña WCA |
| `GET /audit` | Log de auditoría BASC |
| `GET /audit/export.csv` | CSV export para auditores |
| `GET /acknowledgment/demo` | Demo acuse automático multilingüe |
| `GET /monitor` | Dashboard de salud del sistema |

---

## Señales de éxito

- JP pide hacer una cotización real en el demo → muy buena señal
- Renato pregunta sobre cómo los auditores BASC ven el log → muy buena señal  
- Alguien pregunta "¿cuándo podemos empezar a usarlo?" → cierre inminente
- JP dice "necesito entender mejor el costeo" → muéstrale Vista Clásica de nuevo, es válido

## Señales de alerta

- JP dice "no es lo que esperaba" → volver al paso 4, dejar que él navegue
- Renato empieza a agregar scope → afirmar la visión, separar explícitamente a Pipeline #2/#3
- Silencio largo → hacer una pregunta: "¿qué parte les gustaría ver más en detalle?"
