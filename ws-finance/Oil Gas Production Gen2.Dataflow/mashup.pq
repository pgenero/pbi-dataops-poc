section Section1;
shared oil_gas_2026 = let
  Source = Csv.Document(Web.Contents("http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/fb7a47a0-cba9-4667-a004-6f6c1c346c23/download/produccin-de-pozos-de-gas-y-petrleo-2026.csv"), [Delimiter = ",", Columns = 38, Encoding = 65001, QuoteStyle = QuoteStyle.None]),
  #"Promoted headers" = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
  #"Removed other columns" = Table.SelectColumns(#"Promoted headers", {"anio", "mes", "prod_pet", "prod_gas", "provincia", "tipo_de_recurso"}),
  #"Changed column type" = Table.TransformColumnTypes(#"Removed other columns", {{"anio", Int64.Type}, {"mes", Int64.Type}, {"prod_pet", type number}, {"prod_gas", type number}}),
  #"Grouped rows" = Table.Group(#"Changed column type", {"anio", "mes", "provincia", "tipo_de_recurso"}, {{"oil", each List.Sum([prod_pet]), type nullable number}, {"gas", each List.Sum([prod_gas]), type nullable number}}),
  #"Renamed columns" = Table.RenameColumns(#"Grouped rows", {{"anio", "year"}, {"mes", "month"}})
in
  #"Renamed columns";
