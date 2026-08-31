from app import init_db, sync_vehicle_catalog_all


def progress(index, total, name):
    print(f"[{index}/{total}] {name}")

if __name__ == "__main__":
    print("PH ESTÉTICA & DETAIL — Sincronizando marcas e modelos com a FIPE...")
    print("Esse processo pode levar alguns minutos e só precisa ser feito para pré-carregar o catálogo completo.")
    init_db()
    result = sync_vehicle_catalog_all(progress=progress)
    print("\nConcluído.")
    print(f"Marcas: {result['brands']}")
    print(f"Modelos genéricos processados: {result['generic_models']}")
    print(f"Registros/modelos FIPE usados como referência: {result['raw_models']}")
    if result['errors']:
        print(f"Avisos/erros: {len(result['errors'])}")
        for item in result['errors'][:30]:
            print(" -", item)
        if len(result['errors']) > 30:
            print(" - ...")
    input("\nPressione ENTER para fechar...")
