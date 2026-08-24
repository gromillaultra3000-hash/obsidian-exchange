<?php

namespace App\Filament\Resources\SellOrderResource\Pages;

use App\Filament\Resources\SellOrderResource;
use Filament\Resources\Pages\ListRecords;

class ListSellOrders extends ListRecords
{
    protected static string $resource = SellOrderResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
