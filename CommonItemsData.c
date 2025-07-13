class CommonItemsData
{
    // Use este campo para definir um conjunto fixo de kits de itens.
    ref array<ref array<string>> item_kits;

    // Use este campo para definir múltiplos conjuntos de kits, dos quais um será escolhido aleatoriamente.
    ref array<ref array<ref array<string>>> obfs_random_item_kits;

    void CommonItemsData() {
        item_kits = new array<ref array<string>>;
        obfs_random_item_kits = new array<ref array<ref array<string>>>;
    }
}
