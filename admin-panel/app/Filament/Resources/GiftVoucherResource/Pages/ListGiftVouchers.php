<?php

namespace App\Filament\Resources\GiftVoucherResource\Pages;

use App\Filament\Resources\GiftVoucherResource;
use Filament\Resources\Pages\ListRecords;

class ListGiftVouchers extends ListRecords
{
    protected static string $resource = GiftVoucherResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
