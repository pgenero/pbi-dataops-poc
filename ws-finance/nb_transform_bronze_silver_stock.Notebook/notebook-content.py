# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "aad32722-e4e0-4014-b387-a81e33cfa6c6",
# META       "default_lakehouse_name": "lh_finance_bronze_dev",
# META       "default_lakehouse_workspace_id": "91a851c6-a93e-422c-a353-d4507a456b0a",
# META       "known_lakehouses": [
# META         {
# META           "id": "aad32722-e4e0-4014-b387-a81e33cfa6c6"
# META         },
# META         {
# META           "id": "ecdfe41d-b6f5-41bb-9c33-102a2e09cdfb"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

# ------------------------------------------------------------------------
# CONFIGURACIÓN DE RUTAS Y CAPAS
# ------------------------------------------------------------------------

# Ruta ABFSS origen (Capa Bronze)
# BRONZE_TABLE_PATH = "abfss://FinanceDev@onelake.dfs.fabric.microsoft.com/lh_finance_bronze_dev.Lakehouse/Tables/stock_index/arg_stock_industry"
BRONZE_TABLE_PATH = "abfss://FinanceDev@onelake.dfs.fabric.microsoft.com/lh_finance_bronze_dev.Lakehouse/Tables/inversion/ied_bcra"

# Nombres de referencia para Spark SQL
LAKEHOUSE_NAME = "lh_finance_bronze_dev"
TABLE_NAME = "ied_bcra"

# ------------------------------------------------------------------------
# LECTURA DE DATOS
# ------------------------------------------------------------------------
# Lectura nativa del formato Delta
df_stock_industry = spark.read.format("delta").load(BRONZE_TABLE_PATH)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 1. Definir la columna que se queda fija y las que van a cambiar
id_vars = ["indice_tiempo"]

# 2. Obtener automáticamente todas las columnas numéricas de las industrias
value_vars = [col for col in df_stock_industry.columns if col != "indice_tiempo"]

# 3. Aplicar el UNPIVOT
df_unpivoted = df_stock_industry.unpivot(
    ids=id_vars,
    values=value_vars,
    variableColumnName="atributos",  # Nombre de la nueva columna con los nombres de industrias
    valueColumnName="valor"   # Nombre de la nueva columna con los números/valores
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# ------------------------------------------------------------------------
# ESCRITURA EN TABLA DELTA
# ------------------------------------------------------------------------

# 1. Definir la ruta de destino (puedes cambiar 'lh_finance_silver_dev' si usas otro lakehouse)
TARGET_LAKEHOUSE = "lh_finance_silver_dev"  # O "lh_finance_silver_dev" si tienes capa silver
TARGET_FOLDER = "inversion"
TARGET_TABLE_NAME = "ied_bcra_unpivoted"

OUTPUT_PATH = f"abfss://FinanceDev@onelake.dfs.fabric.microsoft.com/{TARGET_LAKEHOUSE}.Lakehouse/Tables/{TARGET_FOLDER}/{TARGET_TABLE_NAME}"

try:
    print(f"[INFO] Guardando datos en OneLake: {OUTPUT_PATH}")
    
    # 2. Guardar DataFrame en formato Delta
    # Usamos .mode("overwrite") para reemplazar la tabla si ya existe. Usa "append" si vas a sumar datos nuevos periódicamente.
    df_unpivoted.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(OUTPUT_PATH)
        
    print(f"[OK] Tabla '{TARGET_TABLE_NAME}' guardada exitosamente.")
    
except Exception as e:
    print(f"[ERROR] No se pudo escribir la tabla Delta: {str(e)}")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
